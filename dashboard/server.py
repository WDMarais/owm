"""
Dashboard server — reads real workspace state from disk.

Workspace: set OWM_WORKSPACE env var, or run uvicorn from inside a workspace directory.

Run: OWM_WORKSPACE=~/tmp/owm-walkthrough uvicorn dashboard.server:app --reload
"""
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import psutil
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from owm.config import parse_workspace_config, parse_instance_config

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
    state = _read_state(instance)
    pid   = state.get("pid")
    if not pid or pid == "UNSET":
        return "stopped"
    try:
        return "running" if psutil.pid_exists(int(pid)) else "stopped"
    except Exception:
        return "stopped"


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
    if secs < 0:     return "just now"
    if secs < 120:   return f"{int(secs)}s ago"
    if secs < 3600:  return f"{int(secs // 60)}m ago"
    if secs < 86400: return f"{int(secs // 3600)}h ago"
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
    env = os.environ.copy()
    env["OWM_WORKSPACE"] = str(WORKSPACE)
    result = subprocess.run(
        ["owm", "fetch"],
        cwd=str(WORKSPACE),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return {"ok": result.returncode == 0, "output": result.stdout}


@app.get("/api/status")
def api_status():
    instances = [
        {"name": name, "status": _instance_status(name)}
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
    if not instance_dir.exists():
        return {"error": "not found", "code": "NOT_FOUND"}

    try:
        cfg = parse_instance_config((instance_dir / "instance.toml").read_text())
    except Exception as e:
        return {"error": f"instance.toml unreadable: {e}", "code": "CONFIG_ERROR"}

    state  = _read_state(name)
    pid    = state.get("pid")
    status = _instance_status(name)
    live   = status == "running"

    health = {
        "http":   {"ok": live,  "value": f":{cfg.server.http_port}"},
        "gevent": {"ok": live,  "value": f":{cfg.server.gevent_port}"},
        "db":     {"ok": True,  "value": cfg.database.name},
        "venv":   {"ok": (instance_dir / ".venv").exists(), "value": "ok"},
        "proxy":  {"ok": True,  "value": f"{name}.localhost"},
    }

    repos = [
        {"name": repo_name, "branch": spec.branch,
         "dirty": False,
         "vs_origin_branch":             {"ahead_by": 0, "behind_by": 0},
         "vs_origin_base":               {"ahead_by": 0, "behind_by": 0},
         "origin_branch_vs_origin_base": {"ahead_by": 0, "behind_by": 0}}
        for repo_name, spec in cfg.repos.items()
    ]

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


def _owm(workspace_root: Path, *args: str, timeout: int = 60) -> dict:
    env = os.environ.copy()
    env["OWM_WORKSPACE"] = str(workspace_root)
    result = subprocess.run(
        ["owm", *args],
        cwd=str(workspace_root),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return {"ok": result.returncode == 0, "output": result.stdout + result.stderr}


@app.post("/api/instance/{name}/start")
def api_instance_start(name: str):
    return _owm(WORKSPACE, "start", name)


@app.post("/api/instance/{name}/stop")
def api_instance_stop(name: str):
    return _owm(WORKSPACE, "stop", name)


@app.post("/api/instance/{name}/restart")
def api_instance_restart(name: str):
    return _owm(WORKSPACE, "restart", name, timeout=120)


@app.post("/api/instance/{name}/kill")
def api_instance_kill(name: str):
    return _owm(WORKSPACE, "kill", name)


@app.post("/api/instance/{name}/archive")
def api_instance_archive(name: str):
    return _owm(WORKSPACE, "archive", name)


@app.post("/api/instance/{name}/delete")
def api_instance_delete(name: str):
    return _owm(WORKSPACE, "delete", name, "--force")


@app.post("/api/instance/{name}/rename")
def api_instance_rename(name: str, new_name: str):
    return _owm(WORKSPACE, "rename", name, new_name)


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

    return {"notifications": notifications}


@app.get("/api/logs/{name}/{log}")
def api_logs(name: str, log: str, n: int = 50):
    if log == "owm":
        log_path = WORKSPACE / "owm.log"
        lines = []
        for raw in log_path.read_text().splitlines()[-n:]:
            try:
                e = json.loads(raw)
                parts = [
                    e.get("event", ""),
                    e.get("repo") or e.get("instance") or "",
                    e.get("status") or "",
                ]
                text = "  ".join(p for p in parts if p)
                if e.get("pid"):
                    text += f"  pid={e['pid']}"
                lines.append({"ts": e.get("ts"), "level": "info", "text": text.strip()})
            except Exception:
                lines.append({"text": raw})
        return {"lines": lines, "log_path": str(log_path)}

    log_path = WORKSPACE / "instances" / name / "instance.log"
    if not log_path.exists():
        return {"lines": [], "log_path": str(log_path)}
    return {
        "lines":    [{"text": l} for l in log_path.read_text().splitlines()[-n:]],
        "log_path": str(log_path),
    }


# ── Static files ──────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return FileResponse(DASHBOARD / "index.html")

app.mount("/static", StaticFiles(directory=str(DASHBOARD)), name="static")
