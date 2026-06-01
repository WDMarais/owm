"""
Dashboard server — reads real workspace state from disk.

Workspace: set OWM_WORKSPACE env var, or run uvicorn from inside a workspace directory.

Run: OWM_WORKSPACE=~/tmp/owm-walkthrough uvicorn dashboard.server:app --reload
"""
import asyncio
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import psutil
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
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

    repos = []
    for repo_name, spec in cfg.repos.items():
        if spec.shared:
            wt = WORKSPACE / "_shared" / repo_name / spec.branch
        else:
            wt = WORKSPACE / "instances" / name / repo_name
        sync = _repo_sync(wt, spec.branch, spec.base, spec.shared)
        repos.append({"name": repo_name, "branch": spec.branch, "base": spec.base, **sync})

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


def _check_has_remote(worktree: Path, branch: str) -> bool:
    r = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "--verify", f"origin/{branch}"],
        capture_output=True, text=True,
    )
    return r.returncode == 0


def _git_ahead_behind(worktree: Path, ref: str) -> dict:
    r = subprocess.run(
        ["git", "-C", str(worktree), "rev-list", "--count", "--left-right", f"HEAD...{ref}"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return {"ahead_by": 0, "behind_by": 0}
    parts = r.stdout.strip().split()
    if len(parts) != 2:
        return {"ahead_by": 0, "behind_by": 0}
    try:
        return {"ahead_by": int(parts[0]), "behind_by": int(parts[1])}
    except ValueError:
        return {"ahead_by": 0, "behind_by": 0}


def _repo_sync(worktree: Path, branch: str, base: str | None, shared: bool) -> dict:
    _zero = {"ahead_by": 0, "behind_by": 0}
    if not worktree.exists():
        return {
            "dirty": False, "has_remote": False, "last_commit": None,
            "vs_origin_branch": _zero, "vs_origin_base": _zero,
            "origin_branch_vs_origin_base": _zero,
        }

    dirty_r = subprocess.run(
        ["git", "-C", str(worktree), "status", "--porcelain"],
        capture_output=True, text=True,
    )
    dirty = bool(dirty_r.stdout.strip()) if dirty_r.returncode == 0 else False

    has_remote = _check_has_remote(worktree, branch)

    lc = subprocess.run(
        ["git", "-C", str(worktree), "log", "-1", "--format=%h %aI"],
        capture_output=True, text=True,
    )
    last_commit = None
    if lc.returncode == 0 and lc.stdout.strip():
        parts = lc.stdout.strip().split(" ", 1)
        ts = parts[1] if len(parts) > 1 else None
        last_commit = {"hash": parts[0], "ts": ts, "rel": _rel(ts)}

    vs_branch = _git_ahead_behind(worktree, f"origin/{branch}") if has_remote else _zero
    vs_base   = _git_ahead_behind(worktree, f"origin/{base}") if base and not shared else _zero

    ob_vs_ob = _zero
    if base and not shared:
        r = subprocess.run(
            ["git", "-C", str(worktree), "rev-list", "--count", "--left-right",
             f"origin/{branch}...origin/{base}"],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            parts = r.stdout.strip().split()
            if len(parts) == 2:
                try:
                    ob_vs_ob = {"ahead_by": int(parts[0]), "behind_by": int(parts[1])}
                except ValueError:
                    pass

    return {
        "dirty":                        dirty,
        "has_remote":                   has_remote,
        "last_commit":                  last_commit,
        "vs_origin_branch":             vs_branch,
        "vs_origin_base":               vs_base,
        "origin_branch_vs_origin_base": ob_vs_ob,
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


@app.post("/api/instance/{name}/sync/{repo}")
def api_instance_sync(name: str, repo: str):
    return _owm(WORKSPACE, "sync", name, "--repo", repo)


@app.post("/api/instance/{name}/push/{repo}")
def api_instance_push(name: str, repo: str):
    return _owm(WORKSPACE, "push", name, "--repo", repo)


@app.get("/api/processes")
def api_processes():
    managed     = []
    managed_pids = set()

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
                if status == "running":
                    managed_pids.add(pid_int)
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

    # Exclude worker children of managed master pids from orphan scan
    managed_family: set[int] = set(managed_pids)
    for entry in managed:
        for w in entry.get("workers", []):
            managed_family.add(w["pid"])

    orphaned = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            if proc.pid in managed_family:
                continue
            cmdline = proc.info.get("cmdline") or []
            if not any("odoo-bin" in c for c in cmdline):
                continue
            name = str(proc.pid)
            for i, arg in enumerate(cmdline):
                if arg == "--config" and i + 1 < len(cmdline):
                    name = Path(cmdline[i + 1]).parent.name
                    break
            ports: list[int] = []
            try:
                ports = [c.laddr.port for c in proc.net_connections() if c.status == "LISTEN"]
            except Exception:
                pass
            orphaned.append({"name": name, "pid": proc.pid, "ports": ports})
        except Exception:
            pass

    return {"managed": managed, "orphaned": orphaned, "unregistered": [], "squatters": []}


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
            wt = WORKSPACE / "_shared" / repo_name / spec.branch if spec.shared else WORKSPACE / "instances" / name / repo_name
            if not _check_has_remote(wt, spec.branch):
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
    lines = [fmt(l) if fmt else {"text": l} for l in tail]
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
    import uvicorn
    port = int(os.environ.get("PORT", 8090))
    uvicorn.run("dashboard.server:app", host="127.0.0.1", port=port)
