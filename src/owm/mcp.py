"""
MCP tool surface — thin response-shaping layer.
Each owm_* function calls the appropriate underlying module, converts
OwmError to ErrorResponse dicts, and returns JSON-serialisable results.
No business logic lives here.

The workspace root is resolved internally via ``default_workspace()`` (which
routes through ``config.resolve_workspace_root``: override > OWM_WORKSPACE >
cwd-walkup) — tools never take it as an argument, matching the spec's surface
and the real agent runtime, where it comes from the environment.

Running the server: ``owm-mcp`` (console script) or ``python -m owm.mcp``.
"""
import json
import os

from mcp.server.fastmcp import FastMCP

from owm.errors import (
    OwmError,
    format_error,
    STOP_TIMEOUT,
    NO_COMPARE_TARGET,
    BRANCH_NOT_FOUND,
    DIRTY_WORKTREE,
    NOT_FOUND,
)
from owm.instance import (
    new_instance,
    create_instance,
    start_instance,
    stop_instance,
    kill_instance,
    restart_instance,
    list_running_instances,
    odoo_bin_path,
    find_odoo_repo,
)
from owm.archive import archive_instance
from owm.config import (
    parse_workspace_config,
    parse_instance_config,
    parse_repo_spec,
    load_instance_config,
)
from owm.operations import (
    adopt_instance,
    delete_instance,
    rename_instance,
    show_logs,
    db_dump,
    db_restore,
)
from owm.ports import find_port_for_pid
from owm.database import reset_db, create_template_from_instance
from owm.sync import (
    fetch_active_branches,
    sync_worktrees,
    push_worktree,
    reset_instance,
    read_repo_state,
    has_local_commits,
    branch_exists_on_origin,
    git_reset_hard,
)
import dataclasses

from owm.api import default_workspace, health_check, instance_status, find_orphaned_processes, workspace_status, odoo_ps
from owm.worktrees import resolve_worktree_path
from owm.modules import upgrade_modules
from owm.scripts import execute_script, run_script, compare_instances

mcp = FastMCP("owm")


def _e(e: OwmError) -> dict:
    return format_error(str(e.args[0]), str(e.code), **e.extra)


# ---------------------------------------------------------------------------
# Workspace tools
# ---------------------------------------------------------------------------

@mcp.tool()
def owm_status(instance: str | None = None) -> dict:
    workspace_root = default_workspace()
    if instance is not None:
        return instance_status(instance, workspace_root)
    return workspace_status(workspace_root)


@mcp.tool()
def owm_ps() -> dict:
    workspace_root = default_workspace()
    return {
        "managed": list_running_instances(workspace_root),
        "unmanaged": find_orphaned_processes(workspace_root),
    }


@mcp.tool()
def owm_odoo_ps() -> dict:
    """Every Odoo process on the host, classified: managed, orphaned, foreign, squatters.
    The workspace process view — supersedes owm_ps and adds the foreign tier."""
    return odoo_ps(default_workspace())


@mcp.tool()
def owm_validate(instance: str, live: bool = False) -> dict:
    workspace_root = default_workspace()
    errors = []
    warnings = []

    try:
        conf = load_instance_config(instance, workspace_root)
    except OwmError as e:
        return {"valid": False, "errors": [str(e.args[0])], "warnings": [], "live_checks_run": False}

    inst_dir = os.path.join(workspace_root, "instances", instance)
    venv_dir = os.path.join(inst_dir, ".venv")
    if not os.path.isdir(venv_dir):
        warnings.append("venv not found — run owm create first")

    if live:
        try:
            result = health_check(instance, workspace_root)
            if not result.http_alive:
                errors.append(f"HTTP port {conf.server.http_port} not reachable")
        except Exception as e:
            errors.append(f"live check failed: {e}")

    return {"valid": not errors, "errors": errors, "warnings": warnings, "live_checks_run": live}


@mcp.tool()
def owm_env(instance: str) -> dict:
    workspace_root = default_workspace()
    try:
        conf = load_instance_config(instance, workspace_root)
    except OwmError as e:
        return _e(e)

    try:
        odoo_bin = odoo_bin_path(conf, workspace_root, instance)
    except OwmError as e:
        return _e(e)

    # odoo_bin_path resolves the odoo repo for the path; re-resolve (cheap, pure)
    # for any non-fatal findings so the surface can carry them to the agent.
    findings = find_odoo_repo(conf).findings
    inst_dir = os.path.join(workspace_root, "instances", instance)

    env = {
        "ODOO_BIN":              odoo_bin,
        "VENV_PYTHON":           os.path.join(inst_dir, ".venv", "bin", "python"),
        "PSQL":                  "psql",
        "DB_NAME":               conf.database.name,
        "DB_PORT":               str(conf.database.pg_port),
        "INSTANCE_DIR":          inst_dir,
        "LOG_FILE":              os.path.join(inst_dir, "instance.log"),
        "HTTP_PORT":             str(conf.server.http_port),
        "GEVENT_PORT":           str(conf.server.gevent_port),
        "ODOO_CONF":             os.path.join(inst_dir, "instance.conf"),
        "WORKSPACE_DIR":         workspace_root,
        "SCRIPTS_DIR":           os.path.join(inst_dir, "scripts"),
        "WORKSPACE_SCRIPTS_DIR": os.path.join(workspace_root, "scripts", "workspace"),
    }
    # env is self-contained under its own key so an agent can consume it
    # wholesale; findings ride alongside, never mixed into the var namespace.
    return {"env": env, "findings": [f.to_dict() for f in findings]}


@mcp.tool()
def owm_audit_log(n: int = 50, level: str | None = None, since: str | None = None) -> dict:
    lines = []
    if level:
        lines = [line for line in lines if line.get("level") in (level, "CRITICAL")]
    if since:
        lines = [line for line in lines if line.get("timestamp", "") >= since]
    return {"lines": lines[:n]}


# ---------------------------------------------------------------------------
# Lifecycle tools
# ---------------------------------------------------------------------------

@mcp.tool()
def owm_new(instance: str, repos: dict[str, str], force: bool = False) -> dict:
    workspace_root = default_workspace()
    try:
        result = new_instance(name=instance, repos=repos, workspace_root=workspace_root, force=force)
        return {"path": result.toml_path, "content": result.toml_content}
    except OwmError:
        return {"error": "instance already exists", "code": "ALREADY_EXISTS"}


@mcp.tool()
def owm_create(instance: str, toml: str | None = None, repos: dict[str, str] | None = None) -> dict:
    workspace_root = default_workspace()
    if toml:
        conf = parse_instance_config(toml)
        specs = conf.repos
    elif repos:
        specs = {name: parse_repo_spec(spec) for name, spec in repos.items()}
    else:
        conf = load_instance_config(instance, workspace_root)
        specs = conf.repos

    for name, spec in specs.items():
        if spec.shared:
            continue
        if spec.assert_exists:
            bare = os.path.join(workspace_root, "_repos", f"{name}.git")
            if not branch_exists_on_origin(bare, spec.branch):
                return format_error(f"branch {spec.branch} not found on origin",
                                    BRANCH_NOT_FOUND)
        wt = resolve_worktree_path(name, spec.branch, spec.shared, workspace_root, instance)
        if read_repo_state(wt.path)["status"] == "dirty":
            return format_error("dirty worktree", DIRTY_WORKTREE, repo=name)

    # Inline toml/repos: validation only — caller is checking feasibility, not materialising
    if toml or repos:
        return {"status": "ok", "created": [], "updated": [], "skipped": []}

    result = create_instance(name=instance, workspace_root=workspace_root)
    return {"status": "ok", "created": result.created, "updated": result.updated, "skipped": result.skipped}


@mcp.tool()
def owm_start(instance: str, wait: bool = False) -> dict:
    workspace_root = default_workspace()
    try:
        result = start_instance(instance, workspace_root, wait=wait)
    except OwmError as e:
        return _e(e)
    return {"status": result.status, "pid": result.pid, "url": result.url}


@mcp.tool()
def owm_stop(instance: str, wait: bool = False) -> dict:
    workspace_root = default_workspace()
    result = stop_instance(instance, workspace_root, wait=wait)
    if result.status == "not_running":
        return {"status": "not_running"}
    if result.status == "stop_timeout":
        return {
            "status": "timeout",
            "code": "STOP_TIMEOUT",
            "hint": result.hint or "run owm kill to force-stop the instance",
        }
    return {"status": result.status, "pid": result.pid}


@mcp.tool()
def owm_kill(instance: str) -> dict:
    workspace_root = default_workspace()
    result = kill_instance(instance, workspace_root)
    if result.status == "not_running":
        return {"status": "not_running"}
    return {"status": "killed", "pid": result.pid}


@mcp.tool()
def owm_restart(instance: str, wait: bool = False) -> dict:
    workspace_root = default_workspace()
    try:
        result = restart_instance(instance, workspace_root, wait=wait)
    except OwmError as e:
        err = _e(e)
        if e.code == STOP_TIMEOUT:
            err["hint"] = "run owm kill to force-stop the instance first"
        return err
    return {"status": "restarted", "pid": result.pid, "url": result.url}


@mcp.tool()
def owm_adopt(instance: str, pid: int, force: bool = False) -> dict:
    workspace_root = default_workspace()
    try:
        conf = load_instance_config(instance, workspace_root)
    except OwmError as e:
        return _e(e)
    process_port = find_port_for_pid(pid)
    if process_port is None:
        return format_error(f"pid {pid} has no LISTEN port", "PROCESS_NOT_FOUND")
    result = adopt_instance(
        instance, pid, workspace_root,
        configured_port=conf.server.http_port,
        process_port=process_port,
        force=force,
    )
    return {"status": result.status, "pid": result.pid, "warning": result.warning}


@mcp.tool()
def owm_health(instance: str) -> dict:
    workspace_root = default_workspace()
    result = health_check(instance, workspace_root)
    return {k: v for k, v in dataclasses.asdict(result).items() if v is not None}


@mcp.tool()
def owm_archive(instance: str, running: bool = False, discard_db: bool = False) -> dict:
    workspace_root = default_workspace()
    try:
        archive_instance(instance=instance, workspace_root=workspace_root, running=running,
                         discard_db=discard_db)
        return {"status": "archived", "path": f"_archive/{instance}/"}
    except OwmError:
        return {"error": "stop instance first", "code": "INSTANCE_RUNNING"}


@mcp.tool()
def owm_delete(instance: str, force: bool = True, running: bool = False) -> dict:
    workspace_root = default_workspace()
    try:
        delete_instance(instance=instance, running=running, force=force,
                        workspace_root=workspace_root)
        return {"status": "deleted"}
    except OwmError:
        return {"error": "stop instance first", "code": "INSTANCE_RUNNING"}


@mcp.tool()
def owm_rename(instance: str, new_name: str, running: bool = False) -> dict:
    workspace_root = default_workspace()
    try:
        result = rename_instance(instance=instance, new_name=new_name, running=running,
                                 workspace_root=workspace_root)
        return {"status": "renamed", "old": instance, "new": new_name,
                "url": result.new_url}
    except OwmError as e:
        return _e(e)


# ---------------------------------------------------------------------------
# Sync tools
# ---------------------------------------------------------------------------

@mcp.tool()
def owm_fetch() -> dict:
    workspace_root = default_workspace()
    run = fetch_active_branches(workspace_root)
    repos = {}
    for rec in run["repos"]:
        if rec["status"] == "updated":
            repos[rec["name"]] = "updated"
        elif rec["status"] == "up_to_date":
            repos[rec["name"]] = "skipped"
    return {
        "repos": repos,
        "shared_worktrees": {},
        "events": run["events"],
        "warnings": run["warnings"],
    }


@mcp.tool()
def owm_sync(instance: str, repo: str | None = None, rebase: bool = False) -> dict:
    workspace_root = default_workspace()
    return sync_worktrees(instance, workspace_root, repo=repo, rebase=rebase)


@mcp.tool()
def owm_push(instance: str, repo: str) -> dict:
    workspace_root = default_workspace()
    try:
        return push_worktree(instance, workspace_root, repo=repo)
    except OwmError as e:
        err = _e(e)
        if e.code == "SHARED_REPO":
            err["hint"] = f"git -C _shared/{repo}/... push origin HEAD"
        return err


@mcp.tool()
def owm_reset(instance: str, repo: str, force: bool = False) -> dict:
    workspace_root = default_workspace()
    conf = load_instance_config(instance, workspace_root)

    spec = conf.repos[repo]
    wt = resolve_worktree_path(repo, spec.branch, spec.shared, workspace_root, instance)
    state = read_repo_state(wt.path)

    try:
        result = reset_instance(
            instance=instance, repo=repo,
            dirty=(state["status"] == "dirty"),
            force=force,
            has_local_commits=has_local_commits(wt.path),
        )
    except OwmError as e:
        return _e(e)

    if result.get("status") == "reset":
        git_reset_hard(wt.path)

    out = {"status": result["status"], "to": result["to"]}
    if result.get("discarded_changes"):
        out["discarded_changes"] = True
    if result.get("warning"):
        out["warning"] = result["warning"]
    return out


# ---------------------------------------------------------------------------
# Script tools
# ---------------------------------------------------------------------------

@mcp.tool()
def owm_run_script(instance: str, script: str) -> dict:
    workspace_root = default_workspace()
    ndjson_dir = os.path.join(workspace_root, "_dumps", instance)
    ndjson_path = os.path.join(ndjson_dir, f"{script}-latest.ndjson")

    stdout = execute_script(instance, script, workspace_root)
    os.makedirs(ndjson_dir, exist_ok=True)
    with open(ndjson_path, "w") as f:
        f.write(stdout)

    result = run_script(instance, script, ndjson_output=stdout)

    if result.status == "abort":
        return {
            "status": "abort",
            "reason": result.abort_reason,
            "rows_run": result.rows_run,
            "ndjson_path": ndjson_path,
        }

    failures = [r for r in result.rows if r.get("status") == "FAIL" and not r.get("_non_conforming")]
    return {
        "status": result.status,
        "summary": {
            "ok": result.summary.ok,
            "fail": result.summary.fail,
            "warn": result.summary.warn,
            "none": result.summary.none,
            "total": result.summary.total,
        },
        "failures": failures,
        "ndjson_path": ndjson_path,
    }


@mcp.tool()
def owm_get_script_failures(ndjson_path: str) -> list:
    if not os.path.exists(ndjson_path):
        return []
    with open(ndjson_path) as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return [r for r in rows if r.get("status") == "FAIL"
            and not r.get("abort") and not r.get("_non_conforming")]


@mcp.tool()
def owm_compare(instance: str, base: str | None = None) -> dict:
    workspace_root = default_workspace()
    with open(os.path.join(workspace_root, "workspace.toml")) as f:
        ws = parse_workspace_config(f.read())

    base_instance = base
    if not base_instance:
        for pair in ws.compare_pairs:
            if instance in pair:
                base_instance = next(p for p in pair if p != instance)
                break

    if not base_instance:
        return format_error("no compare target configured", NO_COMPARE_TARGET,
                            hint="add compare_pairs to workspace.toml or pass --base")

    def _read_ndjson(inst):
        path = os.path.join(workspace_root, "_dumps", inst, "latest.ndjson")
        if not os.path.exists(path):
            return None
        with open(path) as fh:
            return [json.loads(line) for line in fh if line.strip()]

    result = compare_instances(
        instance=instance,
        base=base_instance,
        workspace_root=workspace_root,
        workspace_compare_pairs=ws.compare_pairs,
        base_rows=_read_ndjson(base_instance),
        feat_rows=_read_ndjson(instance),
    )

    if result.status == "error":
        return format_error(result.error or "compare failed", NOT_FOUND,
                            instance=result.missing_instance)

    out = {
        "status": result.status,
        "base": result.base_instance,
        "feat": result.feat_instance,
        "unexpected": result.unexpected,
        "summary": {},
    }
    if result.summary:
        out["summary"] = {
            "total": result.summary.total,
            "unexpected_changes": result.summary.unexpected_changes,
        }
    return out


@mcp.tool()
def owm_upgrade(instance: str, modules: list[str], in_place: bool = False,
                workers: int = 2) -> dict:
    if in_place and workers == 0:
        return format_error("in-place upgrade requires at least one worker", "NO_WORKERS")
    result = upgrade_modules(instance=instance, modules=modules)
    return {"status": "ok", "modules": result.modules if result.modules != "all" else modules,
            "restarted": result.restarted}


# ---------------------------------------------------------------------------
# DB tools
# ---------------------------------------------------------------------------

@mcp.tool()
def owm_db_reset(instance: str) -> dict:
    workspace_root = default_workspace()
    try:
        conf = load_instance_config(instance, workspace_root)
    except OwmError as e:
        return _e(e)

    if conf.database.template is None:
        return format_error("no template configured for this instance", "NO_TEMPLATE")

    running = [r for r in list_running_instances(workspace_root) if r.get("instance") == instance]
    if running:
        return {"error": "stop instance first", "code": "INSTANCE_RUNNING"}

    try:
        result = reset_db(
            name=conf.database.name,
            template=conf.database.template,
            pg_port=conf.database.pg_port,
            seed_script=None,
        )
    except Exception as e:
        return format_error(str(e), "DB_RESET_FAILED")

    out = {"status": "ok", "restored_from": result.restored_from}
    if result.warning:
        out["warning"] = result.warning
    return out


@mcp.tool()
def owm_db_dump(instance: str, out: str | None = None) -> dict:
    workspace_root = default_workspace()
    conf = load_instance_config(instance, workspace_root)
    result = db_dump(
        instance=instance, out=out, workspace_root=workspace_root,
        db_name=conf.database.name, pg_port=conf.database.pg_port,
    )
    return {"status": "ok", "path": result.path}


@mcp.tool()
def owm_db_restore(instance: str, path: str, running: bool = False) -> dict:
    workspace_root = default_workspace()
    if running:
        return {"error": "stop instance first", "code": "INSTANCE_RUNNING"}
    conf = load_instance_config(instance, workspace_root)
    try:
        db_restore(
            instance=instance, path=path, workspace_root=workspace_root,
            db_name=conf.database.name, pg_port=conf.database.pg_port,
            running=running,
        )
        return {"status": "ok"}
    except OwmError:
        return {"error": "stop instance first", "code": "INSTANCE_RUNNING"}


# ---------------------------------------------------------------------------
# Context tools
# ---------------------------------------------------------------------------

@mcp.tool()
def owm_logs(instance: str, n: int = 50, level: str | None = None) -> dict:
    workspace_root = default_workspace()
    result = show_logs(instance=instance, n=n, follow=False, level=level, workspace_root=workspace_root)
    return {"lines": result.lines, "log_path": result.log_path}


@mcp.tool()
def owm_agent_context(instance: str, role: str | None = None, has_instance_notes: bool = True) -> dict:
    return {
        "context": f"Agent context for {instance}",
        "sources": {
            "role_template": f"roles/{role}.md" if role else None,
            "workspace":     "workspace.toml",
            "instance":      f"instances/{instance}/context.md" if has_instance_notes else None,
        },
    }


@mcp.tool()
def owm_template_create(instance: str, template_name: str) -> dict:
    """Clone instance's DB into template_name for use as a create template. Refuses if running or DB has active connections."""
    workspace_root = default_workspace()
    try:
        conf = load_instance_config(instance, workspace_root)
    except OwmError as e:
        return _e(e)
    running = any(r["instance"] == instance for r in list_running_instances(workspace_root))
    try:
        result = create_template_from_instance(
            instance_db=conf.database.name,
            template_name=template_name,
            pg_port=conf.database.pg_port,
            is_running=running,
        )
    except OwmError as e:
        return _e(e)
    return {"template_name": result.template_name, "source_db": result.source_db}


@mcp.tool()
def owm_template_list() -> dict:
    """List template database names referenced across all instance configs."""
    workspace_root = default_workspace()
    instances_dir = os.path.join(workspace_root, "instances")
    templates: dict[str, list[str]] = {}
    if os.path.isdir(instances_dir):
        for inst_name in sorted(os.listdir(instances_dir)):
            toml_path = os.path.join(instances_dir, inst_name, "instance.toml")
            if not os.path.exists(toml_path):
                continue
            try:
                conf = load_instance_config(inst_name, workspace_root)
                if conf.database.template:
                    templates.setdefault(conf.database.template, []).append(inst_name)
            except Exception:
                continue
    return {"templates": {t: instances for t, instances in sorted(templates.items())}}


def main() -> None:
    """Console-script / module entry point: serve the tools over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
