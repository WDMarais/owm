import json
import os
import re
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

import psutil

from owm.addons import resolve_addons_path
from owm.config import parse_instance_config, parse_workspace_config, InstanceConfig
from owm.errors import OwmError, ALREADY_EXISTS, START_TIMEOUT, STOP_TIMEOUT, NO_ODOO_REPO, PORT_CONTESTED
from owm.oplog import workspace_log, instance_separator
from owm.ports import assign_port, find_conflicting_process
from owm.proxy import get_proxy_backend
from owm.venv import create_venv
from owm.worktrees import create_worktree, resolve_worktree_path


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
    proxy_block_written: bool = False
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


def _build_start_command(
    instance: str, workspace_root: str, conf: InstanceConfig,
    *, init_modules: list[str] | None = None,
) -> list[str]:
    odoo_repo, odoo_spec = find_odoo_repo(conf)
    wt = resolve_worktree_path(odoo_repo, odoo_spec.branch, True, workspace_root, instance)
    python = os.path.join(workspace_root, "instances", instance, ".venv", "bin", "python")
    odoo_bin = os.path.join(wt.path, "odoo-bin")
    conf_file = os.path.join(workspace_root, "instances", instance, "instance.conf")
    cmd = [python, odoo_bin, "--config", conf_file]
    if init_modules:
        cmd += ["-i", ",".join(init_modules)]
    return cmd


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


def _create_instance_db(db_name: str, pg_port: int) -> None:
    r = subprocess.run(
        ["psql", "-h", "/var/run/postgresql", "-p", str(pg_port), "-d", "postgres",
         "-tAc", f"SELECT 1 FROM pg_database WHERE datname='{db_name}'"],
        capture_output=True, text=True,
    )
    if r.returncode == 0 and "1" in r.stdout:
        return
    subprocess.run(
        ["createdb", "-h", "/var/run/postgresql", "-p", str(pg_port), db_name],
        check=True, capture_output=True,
    )




def _collect_occupied_ports(workspace_root: str, exclude_instance: str) -> set[int]:
    occupied: set[int] = set()
    instances_dir = os.path.join(workspace_root, "instances")
    try:
        for entry in os.scandir(instances_dir):
            if not entry.is_dir() or entry.name == exclude_instance:
                continue
            toml_path = os.path.join(entry.path, "instance.toml")
            if not os.path.exists(toml_path):
                continue
            try:
                with open(toml_path) as f:
                    c = parse_instance_config(f.read())
                occupied.add(c.server.http_port)
                occupied.add(c.server.gevent_port)
            except Exception:
                pass
    except OSError:
        pass
    return occupied


def _query_installed_modules(db_name: str, pg_port: int, module_names: list[str]) -> list[str]:
    """Return the subset of module_names already installed in the given DB."""
    if not module_names:
        return []
    names_sql = ", ".join(f"'{m}'" for m in module_names)
    r = subprocess.run(
        ["psql", "-h", "/var/run/postgresql", "-p", str(pg_port), "-d", db_name,
         "-tAc", f"SELECT name FROM ir_module_module WHERE state='installed' AND name IN ({names_sql})"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return []
    return [line.strip() for line in r.stdout.splitlines() if line.strip()]


def _append_modules_to_toml(toml_path: str, new_modules: list[str]) -> tuple[list[str], list[str]]:
    """Add new_modules to [install].modules in place, deduplicating and preserving order.

    Returns (added, already_present) so the caller can report what changed.
    """
    import tomllib
    with open(toml_path) as f:
        content = f.read()
    existing = tomllib.loads(content).get("install", {}).get("modules", [])
    existing_set = set(existing)
    added = [m for m in new_modules if m not in existing_set]
    already_present = [m for m in new_modules if m in existing_set]
    merged = list(dict.fromkeys(existing + added))
    modules_line = f'modules = {merged!r}'.replace("'", '"')
    if re.search(r'^\[install\]', content, re.MULTILINE):
        if re.search(r'^modules\s*=', content, re.MULTILINE):
            content = re.sub(r'^modules\s*=.*$', modules_line, content, flags=re.MULTILINE)
        else:
            content = re.sub(r'(\[install\])', rf'\1\n{modules_line}', content)
    else:
        content = content.rstrip() + f'\n\n[install]\n{modules_line}\n'
    with open(toml_path, "w") as f:
        f.write(content)
    return added, already_present


def _rewrite_ports_in_toml(toml_path: str, http_port: int, gevent_port: int) -> None:
    with open(toml_path) as f:
        content = f.read()
    content = re.sub(r'(http_port\s*=\s*)\d+', rf'\g<1>{http_port}', content)
    content = re.sub(r'(gevent_port\s*=\s*)\d+', rf'\g<1>{gevent_port}', content)
    with open(toml_path, "w") as f:
        f.write(content)


def new_instance(name: str, repos: dict, workspace_root: str, *, force: bool = False) -> NewResult:
    toml_path = os.path.join(workspace_root, "instances", name, "instance.toml")
    if os.path.exists(toml_path) and not force:
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

    # Fresh materialisation: read toml, create all resources
    toml_path = os.path.join(workspace_root, "instances", name, "instance.toml")
    with open(toml_path) as f:
        conf = parse_instance_config(f.read())

    ws_toml_path = os.path.join(workspace_root, "workspace.toml")
    with open(ws_toml_path) as f:
        ws_conf = parse_workspace_config(f.read())

    # Assign port: use pinned port if free, otherwise pick from the default range
    occupied = _collect_occupied_ports(workspace_root, exclude_instance=name)
    if conf.server.http_port in occupied:
        pair = assign_port({"range": [8100, 8299], "occupied": occupied})
        http_port, gevent_port = pair.http_port, pair.gevent_port
        _rewrite_ports_in_toml(toml_path, http_port, gevent_port)
    else:
        http_port, gevent_port = conf.server.http_port, conf.server.gevent_port

    # Worktrees (shared repos get a linked path; per-instance get their own)
    for repo_name, spec in conf.repos.items():
        create_worktree(
            repo_name, spec.branch, spec.shared, workspace_root, name,
            base=spec.base, assert_exists=spec.assert_exists, create=spec.create,
        )

    # Addons paths from workspace repo metadata
    workspace_repos_meta = {
        n: {"has_addons": r.has_addons, "addons_paths": r.addons_paths}
        for n, r in ws_conf.repos.items()
    }
    instance_repos_dict = {
        n: {"shared": s.shared, "branch": s.branch}
        for n, s in conf.repos.items()
    }
    addons_paths = resolve_addons_path(
        workspace_repos=workspace_repos_meta,
        instance_repos=instance_repos_dict,
        workspace_root=workspace_root,
        instance_name=name,
        instances_dir=ws_conf.defaults.instances_dir,
    )

    # Venv
    python_version = conf.python.version if conf.python else "3.12"
    venv_dir = os.path.join(workspace_root, "instances", name, ".venv")
    if not os.path.exists(venv_dir):
        odoo_repo_name, odoo_spec = find_odoo_repo(conf)
        odoo_wt = resolve_worktree_path(odoo_repo_name, odoo_spec.branch, True, workspace_root, name)
        req_files = []
        default_req = os.path.join(odoo_wt.path, "requirements.txt")
        if os.path.exists(default_req):
            req_files.append(default_req)
        create_venv(name, python_version, req_files, patches=[], venv_dir=venv_dir)

    # Database
    _create_instance_db(conf.database.name, conf.database.pg_port)

    # Reverse-proxy block
    domain_suffix = ws_conf.proxy.domain_suffix if ws_conf.proxy else "localhost"
    proxy = get_proxy_backend(ws_conf.proxy)
    if proxy:
        proxy.write_instance(name, http_port, gevent_port, domain_suffix, workspace_root)

    # odoo.conf
    log_path = os.path.join(workspace_root, "instances", name, "instance.log")
    conf_content = generate_instance_conf(
        name,
        http_port,
        gevent_port,
        conf.server.workers,
        db_name=conf.database.name,
        db_port=conf.database.pg_port,
        proxy_active=True,
        addons_path=addons_paths or None,
        logfile=log_path,
    )
    conf_path = os.path.join(workspace_root, "instances", name, "instance.conf")
    with open(conf_path, "w") as f:
        f.write(conf_content)

    return CreateResult(
        status="created",
        worktrees_created=True,
        db_created=True,
        port_reserved=True,
        proxy_block_written=proxy is not None,
        odoo_conf_generated=True,
    )


def start_instance(
    instance: str,
    workspace_root: str,
    *,
    wait: bool = False,
    timeout_seconds: int = 30,
    init_modules: list[str] | None = None,
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

    for port in (conf.server.http_port, conf.server.gevent_port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                raise OwmError(
                    f"port {port} is already in use",
                    code=PORT_CONTESTED,
                    port=port,
                )

    cmd = _build_start_command(instance, workspace_root, conf, init_modules=init_modules)
    log_path = os.path.join(workspace_root, "instances", instance, "instance.log")
    instance_separator(log_path, f"{instance} started")
    log_fh = open(log_path, "a")
    proc = subprocess.Popen(cmd, stdout=log_fh, stderr=log_fh)
    _write_pid(instance, workspace_root, proc.pid)
    workspace_log(workspace_root, "start", instance=instance, pid=proc.pid, status="dispatched")

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
        log_path = os.path.join(workspace_root, "instances", instance, "instance.log")
        instance_separator(log_path, f"{instance} stopped")
        workspace_log(workspace_root, "stop", instance=instance, pid=pid, status="ok")
        return StopResult(status="stopped", pid=pid, events_emitted=["instance_stopped"])

    workspace_log(workspace_root, "stop", instance=instance, pid=pid, status="timeout")
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
    log_path = os.path.join(workspace_root, "instances", instance, "instance.log")
    instance_separator(log_path, f"{instance} killed")
    workspace_log(workspace_root, "kill", instance=instance, pid=pid, status="ok")
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
    addons_path: list[str] | None = None,
    logfile: str | None = None,
) -> str:
    # dbfilter is only safe when subdomain routing is active (feat-789.localhost);
    # without it, all instances share localhost and dbfilter causes session cookie collisions.
    lines = [
        "[options]",
        f"http_port = {http_port}",
        f"gevent_port = {gevent_port}",
        f"workers = {workers}",
        "db_host = /var/run/postgresql",
    ]
    if db_name:
        lines.append(f"db_name = {db_name}")
    if db_port:
        lines.append(f"db_port = {db_port}")
    if proxy_active:
        lines.append(f"dbfilter = ^{instance_name}$")
    if addons_path:
        lines.append(f"addons_path = {','.join(addons_path)}")
    if logfile:
        lines.append(f"logfile = {logfile}")
    return "\n".join(lines) + "\n"
