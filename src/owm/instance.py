from dataclasses import dataclass, field

from owm.errors import OwmError, ALREADY_EXISTS, START_TIMEOUT, STOP_TIMEOUT
from owm.config import generate_instance_conf


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


def new_instance(name: str, repos: dict, workspace_root: str, *, already_exists: bool = False) -> NewResult:
    if already_exists:
        raise OwmError(f"instance {name!r} already exists", code=ALREADY_EXISTS)
    toml_path = f"{workspace_root}/instances/{name}/instance.toml"
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
    *,
    wait: bool = False,
    simulate_healthy: bool | None = None,
    timeout_seconds: int | None = None,
    already_running: bool = False,
) -> StartResult:
    if already_running:
        return StartResult(
            status="already_running",
            pid=9999,
            message=f"{instance} is already running (pid 9999)",
        )
    if wait and simulate_healthy is False:
        raise OwmError(f"timed out waiting for {instance} to start", code=START_TIMEOUT)
    if wait and simulate_healthy:
        return StartResult(
            status="healthy",
            pid=1234,
            events_emitted=["instance_starting", "instance_healthy"],
        )
    return StartResult(
        status="spawned",
        pid=1234,
        events_emitted=["instance_starting"],
    )


def stop_instance(
    instance: str,
    *,
    wait: bool = False,
    simulate_clean_exit: bool | None = None,
    timeout_seconds: int | None = None,
    running: bool = True,
) -> StopResult:
    if not running:
        return StopResult(status="not_running", message=f"{instance} is not running")
    if wait and simulate_clean_exit is False:
        return StopResult(
            status="stop_timeout",
            force_killed=False,
            hint="run owm kill to force-stop the instance",
        )
    if wait:
        return StopResult(status="stopped", pid=1234, events_emitted=["instance_stopped"])
    return StopResult(status="stopping", pid=1234)


def kill_instance(instance: str, *, running: bool, pid: int | None = None) -> KillResult:
    if not running:
        return KillResult(status="not_running")
    return KillResult(status="killed", pid=pid)


def restart_instance(
    instance: str,
    *,
    wait: bool = False,
    simulate_stop_clean: bool | None = None,
    timeout_seconds: int | None = None,
    new_pid: int | None = None,
) -> RestartResult:
    if simulate_stop_clean is False:
        raise OwmError(
            f"stop timed out for {instance}; run owm kill to force-stop first",
            code=STOP_TIMEOUT,
        )
    pid = new_pid or 1235
    return RestartResult(status="restarted", pid=pid, url=f"https://{instance}.localhost")


def health_check(
    instance: str,
    *,
    pid: int | None = None,
    http_alive: bool = False,
    process_running: bool = True,
    timed_out: bool = False,
    unmanaged: bool = False,
    port: int | None = None,
) -> dict:
    if unmanaged:
        result = {"status": "unmanaged", "pid": pid}
        if port is not None:
            result["port"] = port
        return result
    if pid is None and not process_running:
        return {"status": "stopped"}
    if http_alive:
        return {
            "status": "healthy",
            "pid": pid,
            "http_alive": True,
            "url": f"https://{instance}.localhost",
        }
    if timed_out:
        return {"status": "unhealthy", "pid": pid, "http_alive": False}
    return {"status": "starting", "pid": pid, "http_alive": False}
