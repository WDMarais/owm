import json
import os
import signal
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

import psutil

from owm.config import parse_instance_config, InstanceConfig
from owm.errors import OwmError, ALREADY_EXISTS, START_TIMEOUT, STOP_TIMEOUT, NO_ODOO_REPO
from owm.ports import find_conflicting_process
from owm.worktrees import resolve_worktree_path


@dataclass
class NewResult:
    toml_path: str
    toml_content: str
    materialised: bool = False


@dataclass
class CreateResult:
    status: str
    created: list = field(default_factory=list)
    updated: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)
    worktrees_created: bool = False
    db_created: bool = False
    port_reserved: bool = False
    nginx_block_written: bool = False
    odoo_conf_generated: bool = False
    removed_worktrees: list = field(default_factory=list)
    branches_deleted: list = field(default_factory=list)


@dataclass
class StartResult:
    status: str
    pid: int | None = None
    events_emitted: list = field(default_factory=list)
    message: str | None = None
    url: str | None = None


@dataclass
class StopResult:
    status: str
    pid: int | None = None
    events_emitted: list = field(default_factory=list)
    hint: str | None = None
    message: str | None = None
    force_killed: bool = False


@dataclass
class KillResult:
    status: str
    pid: int | None = None


@dataclass
class RestartResult:
    status: str
    pid: int | None = None
    url: str | None = None


_PID_UNSET = "UNSET"


def _state_file_path(instance: str, workspace_root: str) -> str:
    return os.path.join(workspace_root, "instances", instance, "state.json")


def _read_state(instance: str, workspace_root: str) -> dict:
    try:
        with open(_state_file_path(instance, workspace_root)) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _write_state(instance: str, workspace_root: str, state: dict) -> None:
    with open(_state_file_path(instance, workspace_root), "w") as f:
        json.dump(state, f)


def _read_pid(instance: str, workspace_root: str) -> int | None:
    state = _read_state(instance, workspace_root)
    if not state:
        return None  # state.json absent — never started
    pid_val = state["pid"]  # KeyError = malformed state.json, let it propagate
    if pid_val == _PID_UNSET:
        return None
    return int(pid_val)


def _write_pid(instance: str, workspace_root: str, pid: int) -> None:
    state = _read_state(instance, workspace_root)
    state["pid"] = pid
    _write_state(instance, workspace_root, state)


def _clear_pid(instance: str, workspace_root: str) -> None:
    state = _read_state(instance, workspace_root)
    state["pid"] = _PID_UNSET
    _write_state(instance, workspace_root, state)


def _process_alive(pid: int) -> bool:
    return psutil.pid_exists(pid)


def _wait_for_stop(pid: int, timeout_seconds: int) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _process_alive(pid):
            return True
        time.sleep(1)
    return False


def _probe_http(port: int, timeout: float = 2.0) -> bool:
    url = f"http://localhost:{port}/web"
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except urllib.error.HTTPError:
        return True  # any HTTP response means server is up
    except Exception:
        return False


def find_odoo_repo(conf: InstanceConfig) -> tuple[str, object]:
    """Return (repo_name, spec) for the repo that contains odoo-bin.

    Resolution order:
      1. server.odoo_repo — explicit; works for any topology including per-instance checkouts
      2. the single shared repo — covers the common shared-Odoo setup with no extra config
      3. error with a hint to set odoo_repo explicitly
    """
    if conf.server.odoo_repo:
        name = conf.server.odoo_repo
        if name not in conf.repos:
            raise OwmError(
                f"odoo_repo = {name!r} not found in [repos]; check instance.toml",
                code=NO_ODOO_REPO,
            )
        return name, conf.repos[name]

    shared = [(name, spec) for name, spec in conf.repos.items() if spec.shared]
    if len(shared) == 1:
        return shared[0]

    raise OwmError(
        "cannot locate odoo-bin: "
        + ("multiple shared repos; " if len(shared) > 1 else "no shared repo; ")
        + "set `odoo_repo = \"<name>\"` in [server] of instance.toml",
        code=NO_ODOO_REPO,
    )


def _build_start_command(instance: str, workspace_root: str, conf: InstanceConfig) -> list[str]:
    odoo_repo, odoo_spec = find_odoo_repo(conf)
    wt = resolve_worktree_path(odoo_repo, odoo_spec.branch, True, workspace_root, instance)
    python = os.path.join(workspace_root, "instances", instance, ".venv", "bin", "python")
    odoo_bin = os.path.join(wt.path, "odoo-bin")
    conf_file = os.path.join(workspace_root, "instances", instance, "instance.conf")
    return [python, odoo_bin, "--config", conf_file]


def _wait_for_http(port: int, timeout_seconds: int) -> None:
    # Use /web rather than /web/health: health endpoint only exists in Odoo 16+.
    # Any HTTP response (200, 3xx, 4xx) means the server is accepting connections.
    # Only connection errors (refused, timeout) mean it is not ready yet.
    # TODO: use /web/health on Odoo 16+ for structured health status (DB, modules).
    deadline = time.monotonic() + timeout_seconds
    url = f"http://localhost:{port}/web"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except urllib.error.HTTPError:
            return  # server responded — it's up
        except Exception:
            time.sleep(1)
    raise OwmError(
        f"timed out waiting for instance to start (port {port})",
        code=START_TIMEOUT,
    )


def new_instance(name: str, repos: dict, workspace_root: str) -> NewResult:
    toml_path = os.path.join(workspace_root, "instances", name, "instance.toml")
    if os.path.exists(toml_path):
        raise OwmError(f"instance {name!r} already exists", code=ALREADY_EXISTS)
    repo_lines = "\n".join(f'{repo} = "{spec}"' for repo, spec in repos.items())
    toml_content = f"""[repos]
{repo_lines}

[database]
name = "{name}"
pg_port = 5432

[server]
http_port = 8100
gevent_port = 8101
workers = 2
"""
    os.makedirs(os.path.dirname(toml_path), exist_ok=True)
    with open(toml_path, "w") as f:
        f.write(toml_content)
    return NewResult(toml_path=toml_path, toml_content=toml_content, materialised=False)


def create_instance(
    name: str,
    workspace_root: str,
    *,
    instance_exists: bool = False,
    toml_changed: bool = True,
    repo_changes: list | None = None,
    new_repos: list | None = None,
    removed_repos: list | None = None,
) -> CreateResult:
    if instance_exists and not toml_changed and not repo_changes and not new_repos and not removed_repos:
        return CreateResult(status="up_to_date", created=[], skipped=["all"])

    if repo_changes:
        dirty = [r for r in repo_changes if r.get("dirty")]
        clean = [r for r in repo_changes if not r.get("dirty")]
        if dirty:
            conflicts = [
                {"repo": r["repo"], "options": ["switch", "stash", "abort"]}
                for r in dirty
            ]
            return CreateResult(status="needs_resolution", conflicts=conflicts)
        updated = [{"repo": r["repo"], "action": "switched"} for r in clean]
        return CreateResult(status="updated", updated=updated)

    if new_repos:
        return CreateResult(status="updated", created=list(new_repos))

    if removed_repos:
        return CreateResult(
            status="updated",
            removed_worktrees=list(removed_repos),
            branches_deleted=[],
        )

    return CreateResult(
        status="created",
        worktrees_created=True,
        db_created=True,
        port_reserved=True,
        nginx_block_written=True,
        odoo_conf_generated=True,
    )


def start_instance(
    instance: str,
    workspace_root: str,
    *,
    wait: bool = False,
    timeout_seconds: int = 30,
) -> StartResult:
    pid = _read_pid(instance, workspace_root)
    if pid is not None and _process_alive(pid):
        return StartResult(
            status="already_running",
            pid=pid,
            message=f"{instance} is already running (pid {pid})",
        )

    instance_dir = os.path.join(workspace_root, "instances", instance)
    with open(os.path.join(instance_dir, "instance.toml")) as f:
        conf = parse_instance_config(f.read())

    cmd = _build_start_command(instance, workspace_root, conf)
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _write_pid(instance, workspace_root, proc.pid)

    events = ["instance_starting"]

    if wait:
        try:
            _wait_for_http(conf.server.http_port, timeout_seconds)
        except OwmError as e:
            raise OwmError(str(e.args[0]), code=e.code, pid=proc.pid) from e
        events.append("instance_healthy")
        return StartResult(status="healthy", pid=proc.pid, events_emitted=events)

    return StartResult(status="spawned", pid=proc.pid, events_emitted=events)


def stop_instance(
    instance: str,
    workspace_root: str,
    *,
    wait: bool = False,
    timeout_seconds: int = 30,
) -> StopResult:
    pid = _read_pid(instance, workspace_root)
    if pid is None or not _process_alive(pid):
        return StopResult(status="not_running", message=f"{instance} is not running")

    os.kill(pid, signal.SIGTERM)

    if not wait:
        return StopResult(status="stopping", pid=pid)

    if _wait_for_stop(pid, timeout_seconds):
        _clear_pid(instance, workspace_root)
        return StopResult(status="stopped", pid=pid, events_emitted=["instance_stopped"])

    return StopResult(
        status="stop_timeout",
        force_killed=False,
        hint="run owm kill to force-stop the instance",
    )


def kill_instance(instance: str, workspace_root: str) -> KillResult:
    pid = _read_pid(instance, workspace_root)
    if pid is None or not _process_alive(pid):
        return KillResult(status="not_running")
    os.kill(pid, signal.SIGKILL)
    _clear_pid(instance, workspace_root)
    return KillResult(status="killed", pid=pid)


def restart_instance(
    instance: str,
    workspace_root: str,
    *,
    wait: bool = False,
    timeout_seconds: int = 30,
) -> RestartResult:
    stop_result = stop_instance(instance, workspace_root, wait=True, timeout_seconds=timeout_seconds)
    if stop_result.status == "stop_timeout":
        raise OwmError(
            f"stop timed out for {instance}; run owm kill to force-stop first",
            code=STOP_TIMEOUT,
        )
    start_result = start_instance(instance, workspace_root, wait=wait, timeout_seconds=timeout_seconds)
    return RestartResult(status="restarted", pid=start_result.pid, url=f"https://{instance}.localhost")


def health_check(
    instance: str,
    workspace_root: str,
    *,
    wait: bool = False,
    timeout_seconds: int = 30,
) -> dict:
    instance_dir = os.path.join(workspace_root, "instances", instance)
    with open(os.path.join(instance_dir, "instance.toml")) as f:
        conf = parse_instance_config(f.read())
    port = conf.server.http_port

    pid = _read_pid(instance, workspace_root)
    if pid is None or not _process_alive(pid):
        other = find_conflicting_process(port)
        if other:
            return {"status": "unmanaged", "pid": other["pid"], "port": port}
        return {"status": "stopped"}

    if _probe_http(port):
        return {"status": "healthy", "pid": pid, "http_alive": True, "url": f"https://{instance}.localhost"}

    if not wait:
        return {"status": "starting", "pid": pid, "http_alive": False}

    try:
        _wait_for_http(port, timeout_seconds)
        return {"status": "healthy", "pid": pid, "http_alive": True, "url": f"https://{instance}.localhost"}
    except OwmError:
        return {"status": "unhealthy", "pid": pid, "http_alive": False}


def list_running_instances(workspace_root: str) -> list[dict]:
    instances_dir = os.path.join(workspace_root, "instances")
    result = []
    try:
        entries = list(os.scandir(instances_dir))
    except OSError:
        return result
    for entry in entries:
        if not entry.is_dir():
            continue
        pid = _read_pid(entry.name, workspace_root)
        if pid is None or not _process_alive(pid):
            continue
        h = health_check(entry.name, workspace_root)
        conf_path = os.path.join(entry.path, "instance.toml")
        port = None
        try:
            with open(conf_path) as f:
                conf = parse_instance_config(f.read())
            port = conf.server.http_port
        except Exception:
            pass
        result.append({
            "instance": entry.name,
            "pid": pid,
            "port": port,
            "url": h.get("url"),
            "status": h.get("status"),
        })
    return result


def generate_instance_conf(
    instance_name: str,
    http_port: int,
    gevent_port: int,
    workers: int,
    db_name: str | None = None,
    db_port: int | None = None,
    proxy_active: bool = True,
) -> str:
    # dbfilter is only safe when subdomain routing is active (feat-789.localhost);
    # without it, all instances share localhost and dbfilter causes session cookie collisions.
    lines = [
        "[options]",
        f"http_port = {http_port}",
        f"longpolling_port = {gevent_port}",
        f"workers = {workers}",
        "db_host = /var/run/postgresql",
    ]
    if db_name:
        lines.append(f"db_name = {db_name}")
    if db_port:
        lines.append(f"db_port = {db_port}")
    if proxy_active:
        lines.append(f"dbfilter = ^{instance_name}$")
    return "\n".join(lines) + "\n"
