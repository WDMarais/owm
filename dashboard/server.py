"""
Dashboard server — reads real workspace state from disk.

Workspace: set OWM_WORKSPACE env var, or run uvicorn from inside a workspace directory.

Run: OWM_WORKSPACE=~/tmp/owm-walkthrough uvicorn dashboard.server:app --reload
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import psutil
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from owm.config import parse_workspace_config

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


# ── Static files ──────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return FileResponse(DASHBOARD / "index.html")

app.mount("/static", StaticFiles(directory=str(DASHBOARD)), name="static")
