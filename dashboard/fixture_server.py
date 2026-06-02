"""
Dashboard dev server — serves fixture workspace state against the dashboard UI.
Run: uvicorn dashboard.fixture_server:app --reload
"""
import json
import os
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from dashboard.fixtures import REPO_FETCH_AGES, INSTANCE_REPOS_SYNC, INSTANCE_SCRIPTS, PROCESSES, WORKSPACE_ALERTS
from owm.config import parse_repo_spec

WORKSPACE = Path(__file__).parent.parent / "test_fixtures" / "workspace"
DASHBOARD = Path(__file__).parent

app = FastAPI()

_CLEAN_SYNC = {
    "dirty":                        False,
    "has_remote":                   True,
    "last_commit":                  None,
    "vs_origin_branch":             {"ahead_by": 0, "behind_by": 0},
    "vs_origin_base":               {"ahead_by": 0, "behind_by": 0},
    "origin_branch_vs_origin_base": {"ahead_by": 0, "behind_by": 0},
}


# ── Helpers ────────────────────────────────────────────────────────────────

def _rel(iso: str | None) -> str | None:
    if not iso:
        return None
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    secs = (datetime.now(timezone.utc) - dt).total_seconds()
    if secs < 0:     return "just now"
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
        for name, ts in REPO_FETCH_AGES.items()
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

    FIXTURE_PR_URLS = {
        "feat-789": {"customer-config": "https://bitbucket.org/acme/customer-config/pull-requests/new?source=feat-789-dev&dest=dev"},
    }
    sync = INSTANCE_REPOS_SYNC.get(name, {})
    repos = [
        {"name": repo, "branch": parse_repo_spec(spec).branch,
         "base": parse_repo_spec(spec).base,
         "pr_url": FIXTURE_PR_URLS.get(name, {}).get(repo),
         **sync.get(repo, _CLEAN_SYNC)}
        for repo, spec in cfg.get("repos", {}).items()
    ]

    script_cfg     = cfg.get("scripts", {})
    script_runners = script_cfg.get("runners", {})
    script_state   = INSTANCE_SCRIPTS.get(name, {})
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


@app.get("/api/processes")
def api_processes():
    managed = []
    for entry in PROCESSES["managed"]:
        name = entry["name"]
        instance_dir = WORKSPACE / "instances" / name
        state = _read_state(instance_dir)
        cfg   = _read_toml(instance_dir / "instance.toml") if instance_dir.exists() else {}
        srv   = cfg.get("server", {})
        managed.append({
            "name":   name,
            "pid":    entry["pid"],
            "http":   srv.get("http_port"),
            "gevent": srv.get("gevent_port"),
            "status": state["status"],
        })
    return {
        "managed":      managed,
        "orphaned":     PROCESSES["orphaned"],
        "unregistered": PROCESSES["unregistered"],
        "squatters":    PROCESSES["squatters"],
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


# ── Notifications queue ────────────────────────────────────────────────────

_TIER_ORDER = {"blocking": 0, "attention": 1, "active": 2}

@app.get("/api/notifications")
def api_notifications():
    notifications = []
    now = datetime.now(timezone.utc)

    for inst_name in _instances():
        # Script failures
        for sname, ss in INSTANCE_SCRIPTS.get(inst_name, {}).items():
            if ss.get("status") == "fail":
                notifications.append({
                    "tier": "attention", "instance": inst_name,
                    "msg": f"Scripts: {sname} failed", "section": "scripts",
                })

        # Repo sync issues
        for repo_name, s in INSTANCE_REPOS_SYNC.get(inst_name, {}).items():
            vob    = s.get("vs_origin_branch", {})
            ahead  = vob.get("ahead_by", 0)
            behind = vob.get("behind_by", 0)
            dirty  = s.get("dirty", False)

            if ahead > 0 and behind > 0:
                notifications.append({
                    "tier": "blocking", "instance": inst_name,
                    "msg": f"{repo_name} diverged", "section": "repos",
                })
            elif dirty:
                notifications.append({
                    "tier": "attention", "instance": inst_name,
                    "msg": f"{repo_name} uncommitted changes", "section": "repos",
                })
            elif behind > 0:
                notifications.append({
                    "tier": "attention", "instance": inst_name,
                    "msg": f"{repo_name} {behind} behind", "section": "repos",
                })

    # Stale fetches — workspace-level, one per remote
    for repo_name, ts in REPO_FETCH_AGES.items():
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        age_secs = (now - dt).total_seconds()
        if age_secs > 86400:
            age_str = f"{int(age_secs // 86400)}d ago"
            notifications.append({
                "tier": "attention", "instance": None,
                "msg": f"{repo_name} fetched {age_str}", "section": "remotes",
            })

    # Port squatters — workspace-level
    for sq in PROCESSES.get("squatters", []):
        port = sq["ports"][0] if sq["ports"] else "?"
        notifications.append({
            "tier": "blocking", "instance": None,
            "msg": f"port :{port} squatted", "section": "processes",
        })

    notifications.sort(key=lambda n: _TIER_ORDER.get(n["tier"], 99))
    return {"notifications": notifications}


# ── Fetch + banner ────────────────────────────────────────────────────────

@app.post("/api/fetch")
def api_fetch():
    # In production: git fetch all remotes; fixture is instant
    return {"ok": True}


@app.post("/api/instance/{name}/sync/{repo}")
def api_instance_sync(name: str, repo: str):
    return {"ok": True}


@app.post("/api/instance/{name}/push/{repo}")
def api_instance_push(name: str, repo: str):
    return {"ok": True}


@app.post("/api/instance/{name}/pull-base/{repo}")
def api_instance_pull_base(name: str, repo: str):
    return {"ok": True}


@app.get("/api/banner")
def api_banner():
    return {"alerts": WORKSPACE_ALERTS}


# ── Static files (dashboard UI) ────────────────────────────────────────────

@app.get("/")
def index():
    return FileResponse(DASHBOARD / "index.html")

app.mount("/static", StaticFiles(directory=str(DASHBOARD)), name="static")


def main():
    port = int(os.environ.get("PORT", 8200))
    uvicorn.run("dashboard.fixture_server:app", host="127.0.0.1", port=port)
