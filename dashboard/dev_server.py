"""
Dashboard dev server — serves fixture workspace state against the dashboard UI.
Run: uvicorn dashboard.dev_server:app --reload
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

WORKSPACE = Path(__file__).parent.parent / "test_fixtures" / "workspace"
DASHBOARD = Path(__file__).parent

app = FastAPI()

# ── Fixture data for live-derived state ────────────────────────────────────
# In production these come from git calls and ndjson scan; here they're fixed.

_REPO_FETCH_AGES = {
    "odoo":            "2026-05-18T10:22:28Z",
    "enterprise":      "2026-05-18T08:23:00Z",
    "customer-config": "2026-05-18T10:17:00Z",
}

_INSTANCE_REPOS_SYNC = {
    "dev": {
        "customer-config": {"sync_state": "behind", "behind_by": 3},
        "enterprise":      {"sync_state": "clean"},
        "odoo":            {"sync_state": "clean"},
    },
    "feat-789": {
        "customer-config": {"sync_state": "clean"},
        "enterprise":      {"sync_state": "clean"},
        "odoo":            {"sync_state": "clean"},
    },
    "staging": {
        "customer-config": {"sync_state": "clean"},
        "enterprise":      {"sync_state": "clean"},
        "odoo":            {"sync_state": "clean"},
    },
}

_INSTANCE_SCRIPTS = {
    "dev": {
        "setup":     {"status": "ok",   "last_run_at": "2026-05-18T10:21:00Z"},
        "data-load": {"status": "fail", "last_run_at": "2026-05-18T10:09:00Z"},
        "migrate":   {"status": None,   "last_run_at": None},
    },
    "feat-789": {
        "setup":     {"status": "ok", "last_run_at": "2026-05-17T14:10:00Z"},
        "data-load": {"status": None, "last_run_at": None},
        "migrate":   {"status": None, "last_run_at": None},
    },
    "staging": {
        "setup": {"status": "ok", "last_run_at": "2026-05-16T09:04:00Z"},
    },
}


# ── Helpers ────────────────────────────────────────────────────────────────

def _rel(iso: str | None) -> str | None:
    if not iso:
        return None
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    secs = (datetime.now(timezone.utc) - dt).total_seconds()
    if secs < 120:   return f"{int(secs)}s ago"
    if secs < 3600:  return f"{int(secs // 60)}m ago"
    if secs < 86400: return f"{int(secs // 3600)}h ago"
    return f"{int(secs // 86400)}d ago"

def _read_state(instance_dir: Path) -> dict:
    state_file = instance_dir / "state.json"
    if state_file.exists():
        return json.loads(state_file.read_text())
    return {"status": "stopped"}

def _read_toml(path: Path) -> dict:
    import tomllib
    return tomllib.loads(path.read_text())

def _instances() -> list[str]:
    instances_dir = WORKSPACE / "instances"
    return sorted(p.name for p in instances_dir.iterdir() if p.is_dir())


# ── API endpoints ──────────────────────────────────────────────────────────

@app.get("/api/status")
def api_status():
    instances = []
    for name in _instances():
        state = _read_state(WORKSPACE / "instances" / name)
        instances.append({"name": name, "status": state["status"]})

    repos = [
        {"name": name, "last_fetch": _rel(ts)}
        for name, ts in _REPO_FETCH_AGES.items()
    ]
    return {"instances": instances, "repos": repos}


@app.get("/api/instance/{name}")
def api_instance(name: str):
    instance_dir = WORKSPACE / "instances" / name
    if not instance_dir.exists():
        return {"error": "not found", "code": "NOT_FOUND"}

    state    = _read_state(instance_dir)
    cfg      = _read_toml(instance_dir / "instance.toml")
    srv      = cfg["server"]
    db       = cfg["database"]
    gevent   = srv["gevent_port"]
    proxy_host = f"{name}.localhost"

    health = {
        "http":   {"ok": state["status"] == "running", "value": f":{srv['http_port']}"},
        "gevent": {"ok": state["status"] == "running", "value": f":{gevent}"},
        "db":     {"ok": True, "value": db["name"]},
        "venv":   {"ok": True, "value": "ok"},
        "proxy":  {"ok": True, "value": proxy_host},
    }

    sync = _INSTANCE_REPOS_SYNC.get(name, {})
    repos = [
        {"name": repo, "branch": spec.split(":")[0], **sync.get(repo, {"sync_state": "clean"})}
        for repo, spec in cfg.get("repos", {}).items()
    ]

    script_cfg     = cfg.get("scripts", {})
    script_runners = script_cfg.get("runners", {})
    script_state   = _INSTANCE_SCRIPTS.get(name, {})
    scripts = [
        {
            "name": sname,
            "status":   script_state.get(sname, {}).get("status"),
            "last_run": _rel(script_state.get(sname, {}).get("last_run_at")),
        }
        for sname in script_runners
    ]

    commands = [
        {"label": "shell", "cmd": f"owm shell {name}"},
        {"label": "psql",  "cmd": f"owm psql {name}"},
        {"label": "logs",  "cmd": f"owm logs {name}"},
        {"label": "venv",  "cmd": f"source instances/{name}/.venv/bin/activate"},
    ]

    return {
        "name":       name,
        "status":     state["status"],
        "pid":        state.get("pid"),
        "http_port":  srv["http_port"],
        "gevent_port": gevent,
        "started_at": _rel(state.get("started_at")),
        "health":     health,
        "repos":      repos,
        "scripts":    scripts,
        "commands":   commands,
    }


@app.get("/api/logs/{name}/{log}")
def api_logs(name: str, log: str, n: int = 50):
    if log == "owm":
        log_path = WORKSPACE / "owm.log"
        lines = []
        for raw in log_path.read_text().splitlines()[-n:]:
            entry = json.loads(raw)
            lines.append({
                "ts":    entry["ts"],
                "level": entry["level"],
                "text":  entry["msg"],
            })
        return {"lines": lines, "log_path": str(log_path)}

    log_path = WORKSPACE / "instances" / name / "instance.log"
    if not log_path.exists():
        return {"lines": [], "log_path": str(log_path)}
    raw_lines = log_path.read_text().splitlines()[-n:]
    return {
        "lines":    [{"text": l} for l in raw_lines],
        "log_path": str(log_path),
    }


# ── Static files (dashboard UI) ────────────────────────────────────────────

@app.get("/")
def index():
    return FileResponse(DASHBOARD / "index.html")

app.mount("/", StaticFiles(directory=str(DASHBOARD)), name="static")
