"""
Dashboard server — reads real workspace state from disk.

Workspace: set OWM_WORKSPACE env var, or run uvicorn from inside a workspace directory.

Run: OWM_WORKSPACE=~/tmp/owm-walkthrough uvicorn dashboard.server:app --reload
"""
import asyncio
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import psutil
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from owm.api import odoo_ps
from owm.archive import archive_instance
from owm.config import parse_workspace_config, parse_instance_config, load_instance_config
from owm.errors import OwmError
from owm.worktrees import resolve_worktree_path
from owm.instance import (
    health_check,
    kill_instance,
    restart_instance,
    start_instance,
    stop_instance,
)
from owm.operations import delete_instance, rename_instance
from owm.sync import (
    fetch_active_branches,
    pull_base_instance,
    push_worktree,
    read_remote_url,
    remote_branch_exists,
    repo_sync_status,
    sync_worktrees,
)

# Map the lib's health states to the small set the UI renders (dot colour + badge).
_UI_STATUS = {
    "healthy":   "running",
    "starting":  "starting",
    "unhealthy": "unhealthy",
    "unmanaged": "unmanaged",
    "stopped":   "stopped",
}


def _ui_status(name: str) -> str:
    """UI status for an instance, delegating to the lib's health_check.

    `error` means instance.toml didn't parse (surfaced in the nav so it can be
    fixed); `unmanaged` means a process is on the instance's port but re-owm
    didn't start it (e.g. an instance still running under owm)."""
    try:
        return _UI_STATUS.get(health_check(name, str(WORKSPACE)).status, "stopped")
    except Exception:
        # Fault-isolation boundary: this runs once per instance in the status
        # list, and health_check is NOT exception-bounded — a malformed
        # instance.toml (ConfigError), a missing one (OSError), or a corrupt
        # state.json (KeyError, by design in _read_pid) all surface here. One
        # broken instance must not 500 the whole nav, so any failure → "error".
        return "error"

DASHBOARD = Path(__file__).parent


# ── Workspace ─────────────────────────────────────────────────────────────────

def _find_workspace() -> Path:
    env = os.environ.get("OWM_WORKSPACE")
    if env:
        return Path(env).expanduser().resolve()
    for p in [Path.cwd(), *Path.cwd().parents]:
        if (p / "workspace.toml").exists():
            return p.resolve()
    raise RuntimeError(
        "No workspace found. Set OWM_WORKSPACE or run from inside a workspace directory."
    )


WORKSPACE = _find_workspace()


# ── Disk helpers ──────────────────────────────────────────────────────────────

def _instances() -> list[str]:
    return sorted(
        p.name for p in (WORKSPACE / "instances").iterdir() if p.is_dir()
    )


def _read_state(instance: str) -> dict:
    try:
        return json.loads((WORKSPACE / "instances" / instance / "state.json").read_text())
    except Exception:
        return {}


def _instance_status(instance: str) -> str:
    """Running iff re-owm's managed process is alive, derived from health_check
    rather than a separate psutil/state.json check. Binary projection for the
    processes page; the nav uses the richer _ui_status. (NB "running" here means
    process-alive, spanning health_check's healthy/starting/unhealthy.)"""
    try:
        return ("running"
                if health_check(instance, str(WORKSPACE)).status
                in ("healthy", "starting", "unhealthy")
                else "stopped")
    except Exception:
        return "stopped"


def _pr_url_override(instance_dir: Path, repo: str) -> str | None:
    try:
        return json.loads((instance_dir / "pr_urls.json").read_text()).get(repo)
    except Exception:
        return None


def _speculative_pr_url(worktree: Path, branch: str, base: str | None) -> str | None:
    if not base:
        return None
    remote = read_remote_url(str(worktree))
    if not remote:
        return None
    # SSH: git@bitbucket.org:workspace/repo.git
    # HTTPS: https://bitbucket.org/workspace/repo.git
    m = re.match(r"(?:https?://|git@)([^/:]+)[/:](.+?)(?:\.git)?$", remote)
    if not m:
        return None
    host, path = m.group(1), m.group(2)
    if "bitbucket" in host:
        return f"https://{host}/{path}/pull-requests/new?source={branch}&dest={base}"
    if "github" in host:
        return f"https://{host}/{path}/compare/{base}...{branch}"
    return None


def _fetch_timestamps() -> dict:
    try:
        return json.loads((WORKSPACE / "_fetch_timestamps.json").read_text())
    except Exception:
        return {}


def _rel(iso: str | None) -> str | None:
    if not iso:
        return None
    dt   = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    secs = (datetime.now(timezone.utc) - dt).total_seconds()
    if secs < 0:
        return "just now"
    if secs < 120:
        return f"{int(secs)}s ago"
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    return f"{int(secs // 86400)}d ago"


# ── API ───────────────────────────────────────────────────────────────────────

app = FastAPI()


@app.get("/api/banner")
def api_banner():
    alerts = []
    usage   = shutil.disk_usage(str(WORKSPACE))
    free_gb = usage.free / (1024 ** 3)
    if free_gb < 2:
        alerts.append({"level": "critical", "msg": f"Low disk space: {free_gb:.1f} GB free"})
    elif free_gb < 10:
        alerts.append({"level": "warn", "msg": f"Disk space low: {free_gb:.1f} GB free"})

    pg = subprocess.run(["pg_isready", "-q"], capture_output=True)
    if pg.returncode != 0:
        alerts.append({"level": "critical", "msg": "PostgreSQL unreachable"})

    return {"alerts": alerts}


@app.post("/api/fetch")
def api_fetch():
    try:
        return fetch_active_branches(str(WORKSPACE))
    except OwmError as e:
        return {"error": str(e), "code": e.code}


@app.get("/api/status")
def api_status():
    instances = [
        {"name": name, "status": _ui_status(name)}
        for name in _instances()
    ]

    ws_cfg     = parse_workspace_config((WORKSPACE / "workspace.toml").read_text())
    timestamps = _fetch_timestamps()
    repos = [
        {"name": name, "last_fetch": _rel(timestamps.get(name))}
        for name in ws_cfg.repos
    ]

    return {"instances": instances, "repos": repos}


@app.get("/api/instance/{name}")
def api_instance(name: str):
    instance_dir = WORKSPACE / "instances" / name
    try:
        cfg = load_instance_config(name, str(WORKSPACE))
    except OwmError as e:
        return {"error": str(e.args[0]), "code": str(e.code)}
    except OSError as e:
        return {"error": f"instance.toml unreadable: {e}", "code": "OWM_CONFIG_INVALID"}

    state  = _read_state(name)
    pid    = state.get("pid")
    status = _ui_status(name)
    live   = status == "running"

    health = {
        "http":   {"ok": live,  "value": f":{cfg.server.http_port}"},
        "gevent": {"ok": live,  "value": f":{cfg.server.gevent_port}"},
        "db":     {"ok": True,  "value": cfg.database.name},
        "venv":   {"ok": (instance_dir / ".venv").exists(), "value": "ok"},
        "proxy":  {"ok": True,  "value": f"{name}.localhost"},
    }

    repos = []
    for repo_name, spec in cfg.repos.items():
        worktree = resolve_worktree_path(repo_name, spec.branch, spec.shared, str(WORKSPACE), name)
        wt = Path(worktree.path)
        sync    = _repo_sync(wt, spec.branch, spec.base, spec.shared)
        pr_url  = _pr_url_override(instance_dir, repo_name) or _speculative_pr_url(wt, spec.branch, spec.base)
        repos.append({"name": repo_name, "branch": spec.branch, "base": spec.base, "pr_url": pr_url, **sync})

    runners = cfg.scripts.runners if cfg.scripts else {}
    scripts = [{"name": sname, "status": None, "last_run": None} for sname in runners]

    commands = [
        {"label": "shell", "cmd": f"owm shell {name}"},
        {"label": "psql",  "cmd": f"owm psql {name}"},
        {"label": "logs",  "cmd": f"owm logs {name}"},
        {"label": "venv",  "cmd": f"source instances/{name}/.venv/bin/activate"},
    ]

    return {
        "name":        name,
        "status":      status,
        "pid":         pid if pid and pid != "UNSET" else None,
        "http_port":   cfg.server.http_port,
        "gevent_port": cfg.server.gevent_port,
        "started_at":  _rel(state.get("started_at")),
        "health":      health,
        "repos":       repos,
        "scripts":     scripts,
        "commands":    commands,
    }


def _repo_sync(worktree: Path, branch: str, base: str | None, shared: bool) -> dict:
    # Thin presentation wrapper over the lib's single git-state reader: the lib
    # returns raw data, we add the humanised relative time the UI shows.
    s = repo_sync_status(str(worktree), branch, base, shared)
    if s["last_commit"]:
        s["last_commit"]["rel"] = _rel(s["last_commit"]["ts"])
    return s


def _running(name: str) -> bool:
    """Whether re-owm's managed process for `name` is alive (delete/archive/
    rename take `running` as a trust-the-caller guard arg)."""
    try:
        return health_check(name, str(WORKSPACE)).status in ("healthy", "starting", "unhealthy")
    except Exception:
        return False


@app.post("/api/instance/{name}/start")
def api_instance_start(name: str):
    try:
        r = start_instance(name, str(WORKSPACE))
    except OwmError as e:
        return {"error": str(e), "code": e.code}
    return {"status": r.status, "pid": r.pid}


@app.post("/api/instance/{name}/stop")
def api_instance_stop(name: str):
    try:
        r = stop_instance(name, str(WORKSPACE))
    except OwmError as e:
        return {"error": str(e), "code": e.code}
    return {"status": r.status, "pid": r.pid}


@app.post("/api/instance/{name}/restart")
def api_instance_restart(name: str):
    try:
        r = restart_instance(name, str(WORKSPACE))
    except OwmError as e:
        return {"error": str(e), "code": e.code}
    return {"status": r.status, "pid": r.pid}


@app.post("/api/instance/{name}/kill")
def api_instance_kill(name: str):
    try:
        r = kill_instance(name, str(WORKSPACE))
    except OwmError as e:
        return {"error": str(e), "code": e.code}
    return {"status": r.status, "pid": r.pid}


@app.post("/api/instance/{name}/archive")
def api_instance_archive(name: str):
    try:
        archive_instance(instance=name, workspace_root=str(WORKSPACE), running=_running(name))
    except OwmError as e:
        return {"error": str(e), "code": e.code}
    return {"status": "archived"}


@app.post("/api/instance/{name}/delete")
def api_instance_delete(name: str):
    try:
        delete_instance(instance=name, running=_running(name), force=True, workspace_root=str(WORKSPACE))
    except OwmError as e:
        return {"error": str(e), "code": e.code}
    return {"status": "deleted"}


@app.post("/api/instance/{name}/rename")
def api_instance_rename(name: str, new_name: str):
    try:
        rename_instance(instance=name, new_name=new_name, running=_running(name), workspace_root=str(WORKSPACE))
    except OwmError as e:
        return {"error": str(e), "code": e.code}
    return {"status": "renamed", "old": name, "new": new_name}


@app.post("/api/instance/{name}/sync/{repo}")
def api_instance_sync(name: str, repo: str):
    try:
        return sync_worktrees(name, str(WORKSPACE), repo=repo)
    except OwmError as e:
        return {"error": str(e), "code": e.code}


@app.post("/api/instance/{name}/push/{repo}")
def api_instance_push(name: str, repo: str):
    try:
        return push_worktree(name, str(WORKSPACE), repo=repo)
    except OwmError as e:
        return {"error": str(e), "code": e.code}


@app.post("/api/instance/{name}/pull-base/{repo}")
def api_instance_pull_base(name: str, repo: str):
    try:
        return pull_base_instance(name, str(WORKSPACE), repo=repo)
    except OwmError as e:
        return {"error": str(e), "code": e.code}


@app.post("/api/instance/{name}/repo/{repo}/pr-url")
def api_set_pr_url(name: str, repo: str, url: str):
    instance_dir = WORKSPACE / "instances" / name
    pr_file = instance_dir / "pr_urls.json"
    data = json.loads(pr_file.read_text()) if pr_file.exists() else {}
    data[repo] = url
    pr_file.write_text(json.dumps(data, indent=2))
    return {"ok": True}


@app.get("/api/processes")
def api_processes():
    managed     = []

    for name in _instances():
        state   = _read_state(name)
        pid_raw = state.get("pid")
        status  = _instance_status(name)

        http = gevent = None
        try:
            cfg    = parse_instance_config((WORKSPACE / "instances" / name / "instance.toml").read_text())
            http   = cfg.server.http_port
            gevent = cfg.server.gevent_port
        except Exception:
            pass

        pid_int = None
        if pid_raw and pid_raw != "UNSET":
            try:
                pid_int = int(pid_raw)
            except Exception:
                pass

        workers = []
        if pid_int and status == "running":
            try:
                for child in psutil.Process(pid_int).children(recursive=True):
                    try:
                        cmdline = child.cmdline()
                        if "gevent" in cmdline:
                            wtype = "gevent"
                        else:
                            listen_ports = {c.laddr.port for c in child.net_connections() if c.status == "LISTEN"}
                            wtype = "http" if http and http in listen_ports else "cron"
                        workers.append({"pid": child.pid, "type": wtype})
                    except Exception:
                        pass
            except Exception:
                pass
            workers.sort(key=lambda w: ({"http": 0, "cron": 1, "gevent": 2}.get(w["type"], 3), w["pid"]))

        managed.append({"name": name, "status": status, "pid": pid_int,
                         "http": http, "gevent": gevent, "workers": workers})

    # orphaned/foreign/squatters come from the unified classifier so the dashboard
    # reports the same tiers as `owm odoo-ps` / `owm_odoo_ps` — squatters here are
    # already classifier-filtered (owm-shaped holders of their own port read as
    # orphans, not squatters), and foreign odoo processes get their own tier.
    ps = odoo_ps(str(WORKSPACE))
    orphaned = [{"name": p["instance"], "pid": p["pid"], "ports": []}
                for p in ps["orphaned"]]
    foreign  = [{"cmd": p["cmdline"], "pid": p["pid"], "ports": []}
                for p in ps["foreign"]]
    squatters = [{"cmd": s["name"] or s["cmdline"] or f"pid {s['pid']}",
                  "instance": s["instance"], "pid": s["pid"], "ports": [s["http_port"]]}
                 for s in ps["squatters"]]
    return {"managed": managed, "orphaned": orphaned, "foreign": foreign, "squatters": squatters}


@app.get("/api/notifications")
def api_notifications():
    notifications = []

    ws_cfg     = parse_workspace_config((WORKSPACE / "workspace.toml").read_text())
    timestamps = _fetch_timestamps()

    for repo_name in ws_cfg.repos:
        ts = timestamps.get(repo_name)
        if not ts:
            notifications.append({
                "tier": "warn", "instance": None,
                "msg": f"{repo_name}: never fetched", "section": "repos",
            })
        else:
            age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(ts.replace("Z", "+00:00"))).total_seconds() / 3600
            if age_h > 24:
                notifications.append({
                    "tier": "warn", "instance": None,
                    "msg": f"{repo_name}: last fetch {_rel(ts)}", "section": "repos",
                })

    for name in _instances():
        state = _read_state(name)
        pid   = state.get("pid")
        if pid and pid != "UNSET":
            try:
                if not psutil.pid_exists(int(pid)):
                    notifications.append({
                        "tier": "warn", "instance": name,
                        "msg": f"stale pid {pid} in state.json — instance may have crashed",
                        "section": "health",
                    })
            except Exception:
                pass

        try:
            cfg = parse_instance_config((WORKSPACE / "instances" / name / "instance.toml").read_text())
        except Exception as e:
            notifications.append({
                "tier": "warn", "instance": name,
                "msg": f"instance.toml unreadable: {e}", "section": "health",
            })
            continue
        for repo_name, spec in cfg.repos.items():
            if not spec.assert_exists:
                continue
            worktree = resolve_worktree_path(repo_name, spec.branch, spec.shared, str(WORKSPACE), name)
            if not remote_branch_exists(worktree.path, spec.branch):
                notifications.append({
                    "tier": "warn", "instance": name,
                    "msg": f"{repo_name}: branch '{spec.branch}' marked +exists but not found in fetched refs — run owm fetch, or check if branch was deleted upstream",
                    "section": "repos",
                })

    return {"notifications": notifications}


def _read_log_tail(log_path: Path, n: int, fmt=None) -> dict:
    """Read last n lines and return lines + byte offset at end of read."""
    if not log_path.exists():
        return {"lines": [], "offset": 0}
    with open(log_path, "rb") as f:
        raw = f.read()
        offset = len(raw)
    text = raw.decode("utf-8", errors="replace")
    tail = text.splitlines()[-n:]
    lines = [fmt(line) if fmt else {"text": line} for line in tail]
    return {"lines": lines, "offset": offset}


@app.get("/api/logs/owm")
def api_logs_owm(n: int = 50):
    result = _read_log_tail(WORKSPACE / "owm.log", n, fmt=_format_owm_line)
    return {**result, "log_path": str(WORKSPACE / "owm.log")}


@app.get("/api/logs/{name}/odoo")
def api_logs_instance(name: str, n: int = 50):
    log_path = WORKSPACE / "instances" / name / "instance.log"
    result = _read_log_tail(log_path, n)
    return {**result, "log_path": str(log_path)}


def _format_owm_line(raw: str) -> dict:
    try:
        e = json.loads(raw)
        parts = [e.get("event", ""), e.get("repo") or e.get("instance") or "", e.get("status") or ""]
        text = "  ".join(p for p in parts if p)
        if e.get("pid"):
            text += f"  pid={e['pid']}"
        return {"ts": e.get("ts"), "level": "info", "text": text.strip()}
    except Exception:
        return {"text": raw}


def _sse_tail(log_path: Path, from_offset: int = -1, fmt=None):
    async def generate():
        try:
            f = open(log_path, "rb")
            f.seek(from_offset if from_offset >= 0 else 0, 0 if from_offset >= 0 else 2)
        except FileNotFoundError:
            return
        try:
            while True:
                raw = f.readline()
                if raw:
                    line = raw.decode("utf-8", errors="replace").rstrip()
                    entry = fmt(line) if fmt else {"text": line}
                    yield f"data: {json.dumps(entry)}\n\n"
                else:
                    await asyncio.sleep(0.5)
        finally:
            f.close()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/logs/owm/stream")
async def api_logs_owm_stream(from_offset: int = -1):
    return _sse_tail(WORKSPACE / "owm.log", from_offset=from_offset, fmt=_format_owm_line)


@app.get("/api/logs/{name}/odoo/stream")
async def api_logs_instance_stream(name: str, from_offset: int = -1):
    return _sse_tail(WORKSPACE / "instances" / name / "instance.log", from_offset=from_offset)


# ── Static files ──────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return FileResponse(DASHBOARD / "index.html")

app.mount("/static", StaticFiles(directory=str(DASHBOARD)), name="static")


def main():
    port = int(os.environ.get("OWM_DASHBOARD_PORT", 8090))
    uvicorn.run("dashboard.server:app", host="127.0.0.1", port=port)
