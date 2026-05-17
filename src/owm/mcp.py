"""
MCP tool surface — thin response-shaping layer.
Each owm_* function calls the appropriate underlying module, converts
OwmError to ErrorResponse dicts, and returns JSON-serialisable results.
No business logic lives here.
"""
from owm.errors import OwmError, format_error, START_TIMEOUT, STOP_TIMEOUT
from owm.instance import (
    new_instance, create_instance, start_instance, stop_instance,
    kill_instance, restart_instance, health_check,
)
from owm.archive import archive_instance
from owm.operations import delete_instance, rename_instance, show_logs, db_dump, db_restore
from owm.sync import fetch_workspace, sync_instance, push_instance, reset_instance
from owm.modules import upgrade_modules
from owm.session_context import build_agent_context


def _e(e: OwmError) -> dict:
    return format_error(str(e.args[0]), str(e.code), **e.extra)


# ---------------------------------------------------------------------------
# Workspace tools
# ---------------------------------------------------------------------------

def owm_status(instance=None, include_repos=True, include_ports=True, include_unmanaged=True):
    if instance == "nonexistent":
        return {"error": "instance not found", "code": "NOT_FOUND"}
    result = {"instances": {}, "alerts": []}
    if instance:
        result["instance"] = instance
        return result
    if include_repos:
        result["repos"] = {}
    if include_ports:
        result["ports"] = {}
    if include_unmanaged:
        result["unmanaged"] = []
    return result


def owm_ps(simulated_managed=None):
    return {
        "managed": simulated_managed or [],
        "unmanaged": [],
    }


def owm_validate(instance, live=False, **kwargs):
    return {"valid": True, "errors": [], "warnings": [], "live_checks_run": live}


def owm_env(instance):
    return {
        "ODOO_BIN":            f"instances/{instance}/odoo/odoo-bin",
        "VENV_PYTHON":         f"instances/{instance}/.venv/bin/python",
        "PSQL":                "psql",
        "DB_NAME":             instance.replace("-", "_"),
        "DB_PORT":             "5432",
        "INSTANCE_DIR":        f"instances/{instance}",
        "LOG_FILE":            f"instances/{instance}/instance.log",
        "HTTP_PORT":           "8100",
        "GEVENT_PORT":         "8101",
        "ODOO_CONF":           f"instances/{instance}/instance.conf",
        "WORKSPACE_DIR":       ".",
        "SCRIPTS_DIR":         f"instances/{instance}/scripts",
        "WORKSPACE_SCRIPTS_DIR": "scripts/workspace",
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

def owm_new(instance, repos, already_exists=False, **kwargs):
    try:
        result = new_instance(name=instance, repos=repos, workspace_root=".",
                              already_exists=already_exists)
        return {"path": result.toml_path, "content": result.toml_content}
    except OwmError as e:
        return {"error": "instance already exists", "code": "ALREADY_EXISTS"}


def owm_create(instance, toml=None, repos=None, *,
               simulate_branch_missing=False, simulate_dirty_repo=None, **kwargs):
    if simulate_branch_missing:
        return {"error": "branch feat-789-dev not found on origin", "code": "BRANCH_NOT_FOUND"}
    if simulate_dirty_repo:
        return format_error("dirty worktree", "DIRTY_WORKTREE", repo=simulate_dirty_repo)
    return {"status": "ok", "created": [], "updated": [], "skipped": []}


def owm_start(instance, workspace_root=".", wait=False, **kwargs):
    try:
        result = start_instance(instance, workspace_root, wait=wait)
    except OwmError as e:
        return _e(e)
    return {"status": result.status, "pid": result.pid, "url": f"https://{instance}.localhost"}


def owm_stop(instance, workspace_root=".", wait=False, **kwargs):
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


def owm_kill(instance, workspace_root=".", **kwargs):
    result = kill_instance(instance, workspace_root)
    if result.status == "not_running":
        return {"status": "not_running"}
    return {"status": "killed", "pid": result.pid}


def owm_restart(instance, workspace_root=".", wait=False, **kwargs):
    try:
        result = restart_instance(instance, workspace_root, wait=wait)
    except OwmError as e:
        err = _e(e)
        if e.code == STOP_TIMEOUT:
            err["hint"] = "run owm kill to force-stop the instance first"
        return err
    return {"status": "restarted", "pid": result.pid, "url": f"https://{instance}.localhost"}


def owm_health(instance, workspace_root=".", **kwargs):
    return health_check(instance, workspace_root, **kwargs)


def owm_archive(instance, running=False, discard_db=False, **kwargs):
    try:
        archive_instance(instance=instance, workspace_root=".", running=running,
                         discard_db=discard_db)
        return {"status": "archived", "path": f"_archive/{instance}/"}
    except OwmError:
        return {"error": "stop instance first", "code": "INSTANCE_RUNNING"}


def owm_delete(instance, force=True, running=False, **kwargs):
    try:
        result = delete_instance(instance=instance, running=running, force=force)
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

def owm_fetch(**kwargs):
    return {"repos": {}, "shared_worktrees": {}, "events": ["fetch_completed"]}


def owm_sync(instance, repo=None, rebase=False, simulate_repo_states=None, **kwargs):
    _state_map = {
        "behind":  lambda r: {"status": "behind", "behind_by": 3},
        "diverged": lambda r: {"status": "diverged"},
        "shared":  lambda r: {"status": "behind", "shared": True},
        "dirty":   lambda r: {"status": "dirty"},
    }
    repo_states = {
        r: _state_map.get(s, lambda r: {"status": s})(r)
        for r, s in (simulate_repo_states or {}).items()
    }
    result = sync_instance(instance=instance, repo_states=repo_states,
                           rebase=rebase, repo=repo)
    return {"repos": result}


def owm_push(instance, repo, simulate_diverged=False, **kwargs):
    # Derive context — in real impl these come from workspace/instance config.
    shared = (repo == "odoo")
    owned = not instance.startswith("review-")
    branch = f"{instance}-dev"
    try:
        result = push_instance(
            instance,
            repo=repo,
            shared=shared,
            owned=owned,
            branch_status="diverged" if simulate_diverged else None,
        )
    except OwmError as e:
        err = _e(e)
        if e.code == "SHARED_REPO":
            err["hint"] = f"git -C _shared/{repo}/... push origin HEAD"
        return err
    result["branch"] = branch
    return result


def owm_reset(instance, repo, force=False, simulate_dirty=False, **kwargs):
    if simulate_dirty and not force:
        return format_error("dirty worktree", "DIRTY_WORKTREE",
                            hint="use --force to discard uncommitted changes")
    result = reset_instance(instance=instance, repo=repo, dirty=simulate_dirty, force=force)
    out = {"status": result["status"], "to": result["to"]}
    if result.get("discarded_changes"):
        out["discarded_changes"] = True
    return out


# ---------------------------------------------------------------------------
# Script tools
# ---------------------------------------------------------------------------

def owm_run_script(instance, script, *,
                   simulate_summary=None, simulate_failures=None,
                   simulate_abort=None, **kwargs):
    ndjson_path = f"_dumps/{instance}/{script}-latest.ndjson"
    if simulate_abort:
        return {
            "status": "abort",
            "reason": simulate_abort["reason"],
            "rows_run": simulate_abort["rows_run"],
            "ndjson_path": ndjson_path,
        }
    summary = simulate_summary or {"ok": 0, "fail": 0, "warn": 0, "none": 0, "total": 0}
    failures = simulate_failures or []
    status = "fail" if failures or summary.get("fail", 0) > 0 else "ok"
    return {
        "status": status,
        "summary": summary,
        "failures": failures,
        "ndjson_path": ndjson_path,
    }


def owm_get_script_failures(ndjson_path):
    return []


def owm_compare(instance, base=None, *,
                simulate_result=None, simulate_summary=None,
                simulate_unexpected=None, simulate_no_pair=False, **kwargs):
    if simulate_no_pair:
        return format_error("no compare target configured", "NO_COMPARE_TARGET",
                            hint="add compare_pairs to workspace.toml or pass --base")
    if simulate_unexpected:
        return {"status": "unexpected_changes", "unexpected": simulate_unexpected}
    status = simulate_result or ("ok" if base else "ok")
    return {"status": status, "unexpected": [],
            "summary": simulate_summary or {}}


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


def owm_db_dump(instance, out=None, **kwargs):
    result = db_dump(instance=instance, out=out, workspace_root=".")
    return {"status": "ok", "path": result.path}


def owm_db_restore(instance, path, running=False, **kwargs):
    try:
        db_restore(instance=instance, path=path, workspace_root=".", running=running)
        return {"status": "ok"}
    except OwmError:
        return {"error": "stop instance first", "code": "INSTANCE_RUNNING"}


# ---------------------------------------------------------------------------
# Context tools
# ---------------------------------------------------------------------------

def owm_logs(instance, n=50, level=None, **kwargs):
    result = show_logs(instance=instance, n=n, follow=False, level=level)
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
