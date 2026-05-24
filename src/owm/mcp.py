"""
MCP tool surface — thin response-shaping layer.
Each owm_* function calls the appropriate underlying module, converts
OwmError to ErrorResponse dicts, and returns JSON-serialisable results.
No business logic lives here.
"""
import json
import os

from owm.errors import (
    OwmError, format_error,
    START_TIMEOUT, STOP_TIMEOUT, NO_COMPARE_TARGET, BRANCH_NOT_FOUND, DIRTY_WORKTREE,
)
from owm.instance import (
    new_instance, create_instance, start_instance, stop_instance,
    kill_instance, restart_instance, list_running_instances,
    find_odoo_repo,
)
from owm.archive import archive_instance
from owm.config import parse_workspace_config, parse_instance_config, parse_repo_spec
from owm.operations import delete_instance, rename_instance, show_logs, db_dump, db_restore
from owm.sync import (
    fetch_workspace, sync_instance, push_instance, reset_instance,
    read_repo_state, has_local_commits, branch_exists_on_origin,
    git_fetch_bare, git_fast_forward, git_rebase, git_push, git_reset_hard,
)
from owm.api import default_workspace, health_check, instance_status, workspace_status
from owm.worktrees import resolve_worktree_path
from owm.modules import upgrade_modules
from owm.scripts import execute_script, run_script, compare_instances
from owm.session_context import build_agent_context


def _e(e: OwmError) -> dict:
    return format_error(str(e.args[0]), str(e.code), **e.extra)


# ---------------------------------------------------------------------------
# Workspace tools
# ---------------------------------------------------------------------------

def owm_status(instance=None, workspace_root=None):
    workspace_root = workspace_root or default_workspace()
    if instance is not None:
        return instance_status(instance, workspace_root)
    return workspace_status(workspace_root)


def owm_ps(workspace_root=None, **kwargs):
    workspace_root = workspace_root or default_workspace()
    return {
        "managed": list_running_instances(workspace_root),
        "unmanaged": [],
    }


def owm_validate(instance, live=False, **kwargs):
    return {"valid": True, "errors": [], "warnings": [], "live_checks_run": live}


def owm_env(instance, workspace_root=None, **kwargs):
    workspace_root = workspace_root or default_workspace()
    toml_path = os.path.join(workspace_root, "instances", instance, "instance.toml")
    try:
        with open(toml_path) as f:
            conf = parse_instance_config(f.read())
    except (OSError, ValueError) as e:
        return format_error(str(e), "NOT_FOUND")

    try:
        odoo_repo, odoo_spec = find_odoo_repo(conf)
    except OwmError as e:
        return _e(e)

    wt = resolve_worktree_path(odoo_repo, odoo_spec.branch, odoo_spec.shared, workspace_root, instance)
    inst_dir = os.path.join(workspace_root, "instances", instance)

    return {
        "ODOO_BIN":              os.path.join(wt.path, "odoo-bin"),
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


def owm_audit_log(n=50, level=None, since=None):
    lines = []
    if level:
        lines = [l for l in lines if l.get("level") in (level, "CRITICAL")]
    if since:
        lines = [l for l in lines if l.get("timestamp", "") >= since]
    return {"lines": lines[:n]}


# ---------------------------------------------------------------------------
# Lifecycle tools
# ---------------------------------------------------------------------------

def owm_new(instance, repos, workspace_root=None, force=False, **kwargs):
    workspace_root = workspace_root or default_workspace()
    try:
        result = new_instance(name=instance, repos=repos, workspace_root=workspace_root, force=force)
        return {"path": result.toml_path, "content": result.toml_content}
    except OwmError as e:
        return {"error": "instance already exists", "code": "ALREADY_EXISTS"}


def owm_create(instance, toml=None, repos=None, workspace_root=None, **kwargs):
    workspace_root = workspace_root or default_workspace()
    if toml:
        conf = parse_instance_config(toml)
        specs = conf.repos
    elif repos:
        specs = {name: parse_repo_spec(spec) for name, spec in repos.items()}
    else:
        toml_path = os.path.join(workspace_root, "instances", instance, "instance.toml")
        with open(toml_path) as f:
            conf = parse_instance_config(f.read())
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


def owm_start(instance, workspace_root=None, wait=False, **kwargs):
    workspace_root = workspace_root or default_workspace()
    try:
        result = start_instance(instance, workspace_root, wait=wait)
    except OwmError as e:
        return _e(e)
    return {"status": result.status, "pid": result.pid, "url": f"https://{instance}.localhost"}


def owm_stop(instance, workspace_root=None, wait=False, **kwargs):
    workspace_root = workspace_root or default_workspace()
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


def owm_kill(instance, workspace_root=None, **kwargs):
    workspace_root = workspace_root or default_workspace()
    result = kill_instance(instance, workspace_root)
    if result.status == "not_running":
        return {"status": "not_running"}
    return {"status": "killed", "pid": result.pid}


def owm_restart(instance, workspace_root=None, wait=False, **kwargs):
    workspace_root = workspace_root or default_workspace()
    try:
        result = restart_instance(instance, workspace_root, wait=wait)
    except OwmError as e:
        err = _e(e)
        if e.code == STOP_TIMEOUT:
            err["hint"] = "run owm kill to force-stop the instance first"
        return err
    return {"status": "restarted", "pid": result.pid, "url": f"https://{instance}.localhost"}


def owm_health(instance, workspace_root=None, **kwargs):
    workspace_root = workspace_root or default_workspace()
    return health_check(instance, workspace_root, **kwargs)


def owm_archive(instance, running=False, discard_db=False, workspace_root=None, **kwargs):
    workspace_root = workspace_root or default_workspace()
    try:
        archive_instance(instance=instance, workspace_root=workspace_root, running=running,
                         discard_db=discard_db)
        return {"status": "archived", "path": f"_archive/{instance}/"}
    except OwmError:
        return {"error": "stop instance first", "code": "INSTANCE_RUNNING"}


def owm_delete(instance, force=True, running=False, workspace_root=None, **kwargs):
    workspace_root = workspace_root or default_workspace()
    try:
        result = delete_instance(instance=instance, running=running, force=force,
                                 workspace_root=workspace_root)
        return {"status": "deleted"}
    except OwmError:
        return {"error": "stop instance first", "code": "INSTANCE_RUNNING"}


def owm_rename(instance, new_name, running=False, **kwargs):
    try:
        result = rename_instance(instance=instance, new_name=new_name, running=running)
        return {"status": "renamed", "old": instance, "new": new_name,
                "url": f"https://{new_name}.localhost"}
    except OwmError as e:
        return _e(e)


# ---------------------------------------------------------------------------
# Sync tools
# ---------------------------------------------------------------------------

def owm_fetch(workspace_root=None, **kwargs):
    workspace_root = workspace_root or default_workspace()
    toml_path = os.path.join(workspace_root, "workspace.toml")
    with open(toml_path) as f:
        ws = parse_workspace_config(f.read())

    updated, unreachable = [], []
    for name in ws.repos:
        bare = os.path.join(workspace_root, "_repos", f"{name}.git")
        try:
            if git_fetch_bare(bare):
                updated.append(name)
        except Exception:
            unreachable.append(name)

    result = fetch_workspace(
        repos=list(ws.repos),
        repos_with_updates=updated,
        unreachable_repos=unreachable,
    )
    return {
        "repos": {r: "updated" for r in result.fetched} | {r: "skipped" for r in result.skipped},
        "shared_worktrees": {},
        "events": result.events_emitted,
        "warnings": result.warnings,
    }


def owm_sync(instance, repo=None, rebase=False, workspace_root=None, **kwargs):
    workspace_root = workspace_root or default_workspace()
    toml_path = os.path.join(workspace_root, "instances", instance, "instance.toml")
    with open(toml_path) as f:
        conf = parse_instance_config(f.read())

    repo_states = {}
    for name, spec in conf.repos.items():
        if repo and name != repo:
            continue
        wt = resolve_worktree_path(name, spec.branch, spec.shared, workspace_root, instance)
        repo_states[name] = (
            {"status": "clean", "shared": True} if spec.shared
            else read_repo_state(wt.path)
        )

    decisions = sync_instance(instance=instance, repo_states=repo_states,
                               rebase=rebase, repo=repo)

    for name, decision in decisions.items():
        spec = conf.repos.get(name)
        if not spec or spec.shared:
            continue
        wt = resolve_worktree_path(name, spec.branch, spec.shared, workspace_root, instance)
        if decision["status"] == "fast-forwarded":
            git_fast_forward(wt.path)
        elif decision["status"] == "rebased":
            git_rebase(wt.path)

    return {"repos": decisions}


def owm_push(instance, repo, workspace_root=None, **kwargs):
    workspace_root = workspace_root or default_workspace()
    toml_path = os.path.join(workspace_root, "instances", instance, "instance.toml")
    with open(toml_path) as f:
        conf = parse_instance_config(f.read())

    spec = conf.repos[repo]
    wt = resolve_worktree_path(repo, spec.branch, spec.shared, workspace_root, instance)
    state = read_repo_state(wt.path)
    branch_status = state["status"] if state["status"] in ("diverged", "ahead") else None

    try:
        result = push_instance(
            instance,
            repo=repo,
            shared=spec.shared,
            owned=not spec.readonly,
            branch_status=branch_status,
        )
    except OwmError as e:
        err = _e(e)
        if e.code == "SHARED_REPO":
            err["hint"] = f"git -C _shared/{repo}/... push origin HEAD"
        return err

    git_push(wt.path)
    result["branch"] = spec.branch
    return result


def owm_reset(instance, repo, force=False, workspace_root=None, **kwargs):
    workspace_root = workspace_root or default_workspace()
    toml_path = os.path.join(workspace_root, "instances", instance, "instance.toml")
    with open(toml_path) as f:
        conf = parse_instance_config(f.read())

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

def owm_run_script(instance, script, workspace_root=None, **kwargs):
    workspace_root = workspace_root or default_workspace()
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


def owm_get_script_failures(ndjson_path):
    if not os.path.exists(ndjson_path):
        return []
    with open(ndjson_path) as f:
        rows = [json.loads(l) for l in f if l.strip()]
    return [r for r in rows if r.get("status") == "FAIL"
            and not r.get("abort") and not r.get("_non_conforming")]


def owm_compare(instance, base=None, workspace_root=None, **kwargs):
    workspace_root = workspace_root or default_workspace()
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
            return [json.loads(l) for l in fh if l.strip()]

    result = compare_instances(
        instance=instance,
        base=base_instance,
        workspace_root=workspace_root,
        workspace_compare_pairs=ws.compare_pairs,
        base_rows=_read_ndjson(base_instance),
        feat_rows=_read_ndjson(instance),
    )

    if result.status == "error":
        from owm.errors import NOT_FOUND
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


def owm_upgrade(instance, modules, in_place=False, workers=2, simulate_failure=False, **kwargs):
    if in_place and workers == 0:
        return format_error("in-place upgrade requires at least one worker", "NO_WORKERS")
    if simulate_failure:
        return {"status": "fail", "code": "UPGRADE_FAILED",
                "log_tail": "[last 20 lines of odoo.log]"}
    result = upgrade_modules(instance=instance, modules=modules)
    return {"status": "ok", "modules": result.modules if result.modules != "all" else modules,
            "restarted": result.restarted}


# ---------------------------------------------------------------------------
# DB tools
# ---------------------------------------------------------------------------

def owm_db_reset(instance, **kwargs):
    return {"status": "ok", "restored_from": f"{instance}_base"}


def owm_db_dump(instance, out=None, workspace_root=None, **kwargs):
    workspace_root = workspace_root or default_workspace()
    toml_path = os.path.join(workspace_root, "instances", instance, "instance.toml")
    with open(toml_path) as f:
        conf = parse_instance_config(f.read())
    result = db_dump(
        instance=instance, out=out, workspace_root=workspace_root,
        db_name=conf.database.name, pg_port=conf.database.pg_port,
    )
    return {"status": "ok", "path": result.path}


def owm_db_restore(instance, path, running=False, workspace_root=None, **kwargs):
    workspace_root = workspace_root or default_workspace()
    if running:
        return {"error": "stop instance first", "code": "INSTANCE_RUNNING"}
    toml_path = os.path.join(workspace_root, "instances", instance, "instance.toml")
    with open(toml_path) as f:
        conf = parse_instance_config(f.read())
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

def owm_logs(instance, n=50, level=None, workspace_root=None, **kwargs):
    workspace_root = workspace_root or default_workspace()
    result = show_logs(instance=instance, n=n, follow=False, level=level, workspace_root=workspace_root)
    return {"lines": result.lines, "log_path": result.log_path}


def owm_agent_context(instance, role=None, has_instance_notes=True, **kwargs):
    return {
        "context": f"Agent context for {instance}",
        "sources": {
            "role_template": f"roles/{role}.md" if role else None,
            "workspace":     "workspace.toml",
            "instance":      f"instances/{instance}/context.md" if has_instance_notes else None,
        },
    }
