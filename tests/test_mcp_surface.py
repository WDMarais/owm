"""
Tests for the MCP tool surface: workspace, lifecycle, sync, script, DB, and context tools.
Covers: MCP surface section.

Safety invariants tested explicitly:
- No tool touches upstream destructively
- Push tools refuse unowned/shared branches unconditionally
- Delete/archive/reset tools operate on local state only
"""
import pytest

# TODO: from owm.mcp import (
#     owm_status, owm_ps, owm_validate, owm_env,
#     owm_audit_log, owm_new, owm_create, owm_start,
#     owm_stop, owm_kill, owm_restart, owm_health,
#     owm_archive, owm_delete, owm_rename,
#     owm_fetch, owm_sync, owm_push, owm_reset,
#     owm_run_script, owm_get_script_failures,
#     owm_compare, owm_upgrade, owm_db_reset,
#     owm_db_dump, owm_db_restore, owm_logs,
#     owm_agent_context,
# )

def owm_status(*args, **kwargs):
    raise NotImplementedError

def owm_ps(*args, **kwargs):
    raise NotImplementedError

def owm_validate(*args, **kwargs):
    raise NotImplementedError

def owm_env(*args, **kwargs):
    raise NotImplementedError

def owm_audit_log(*args, **kwargs):
    raise NotImplementedError

def owm_new(*args, **kwargs):
    raise NotImplementedError

def owm_create(*args, **kwargs):
    raise NotImplementedError

def owm_start(*args, **kwargs):
    raise NotImplementedError

def owm_stop(*args, **kwargs):
    raise NotImplementedError

def owm_kill(*args, **kwargs):
    raise NotImplementedError

def owm_restart(*args, **kwargs):
    raise NotImplementedError

def owm_health(*args, **kwargs):
    raise NotImplementedError

def owm_archive(*args, **kwargs):
    raise NotImplementedError

def owm_delete(*args, **kwargs):
    raise NotImplementedError

def owm_rename(*args, **kwargs):
    raise NotImplementedError

def owm_fetch(*args, **kwargs):
    raise NotImplementedError

def owm_sync(*args, **kwargs):
    raise NotImplementedError

def owm_push(*args, **kwargs):
    raise NotImplementedError

def owm_reset(*args, **kwargs):
    raise NotImplementedError

def owm_run_script(*args, **kwargs):
    raise NotImplementedError

def owm_get_script_failures(*args, **kwargs):
    raise NotImplementedError

def owm_compare(*args, **kwargs):
    raise NotImplementedError

def owm_upgrade(*args, **kwargs):
    raise NotImplementedError

def owm_db_reset(*args, **kwargs):
    raise NotImplementedError

def owm_db_dump(*args, **kwargs):
    raise NotImplementedError

def owm_db_restore(*args, **kwargs):
    raise NotImplementedError

def owm_logs(*args, **kwargs):
    raise NotImplementedError

def owm_agent_context(*args, **kwargs):
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Workspace tools — owm_status
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_status_full_workspace():
    result = owm_status()  # TODO: wire up
    assert "instances" in result
    assert "repos" in result or "worktrees" in result
    assert "ports" in result
    assert "alerts" in result


@pytest.mark.mcp_surface
def test_owm_status_single_instance():
    result = owm_status(instance="feat-789")  # TODO: wire up
    assert result["instance"] == "feat-789" or "feat-789" in str(result)


@pytest.mark.mcp_surface
def test_owm_status_selective_include_repos_only():
    result = owm_status(include_repos=True, include_ports=False, include_unmanaged=False)  # TODO: wire up
    assert "repos" in result or "worktrees" in result
    assert "ports" not in result or result.get("ports") is None


@pytest.mark.mcp_surface
def test_owm_status_instance_not_found():
    result = owm_status(instance="nonexistent")  # TODO: wire up
    assert result == {"error": "instance not found", "code": "NOT_FOUND"}


# ---------------------------------------------------------------------------
# Workspace tools — owm_ps
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_ps_returns_managed_and_unmanaged():
    result = owm_ps()  # TODO: wire up
    assert "managed" in result
    assert "unmanaged" in result


@pytest.mark.mcp_surface
def test_owm_ps_managed_entry_shape():
    result = owm_ps(
        simulated_managed=[{"instance": "feat-789", "pid": 1234, "port": 8142, "url": "https://feat-789.localhost", "status": "healthy"}]
    )  # TODO: wire up
    entry = result["managed"][0]
    assert "instance" in entry
    assert "pid" in entry
    assert "port" in entry
    assert "url" in entry
    assert "status" in entry


@pytest.mark.mcp_surface
def test_owm_ps_reads_only_state_json():
    """owm_ps reads state.json per instance — no git calls, no toml parsing.
    Performance contract: reads instances/*/state.json only; enforced via integration
    test with subprocess mocking, not assertable here as a unit test.
    Structural check: result shape is correct regardless of source.
    """
    result = owm_ps()  # TODO: wire up
    assert "managed" in result
    assert "unmanaged" in result


# ---------------------------------------------------------------------------
# Workspace tools — owm_validate
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_validate_static_valid():
    result = owm_validate(instance="feat-789")  # TODO: wire up
    assert "valid" in result
    assert "errors" in result
    assert "warnings" in result
    assert isinstance(result["errors"], list)


@pytest.mark.mcp_surface
def test_owm_validate_live_richer_errors():
    result = owm_validate(instance="feat-789", live=True)  # TODO: wire up
    assert result["valid"] in (True, False)
    assert isinstance(result["errors"], list)


# ---------------------------------------------------------------------------
# Workspace tools — owm_env
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_env_returns_all_required_keys():
    result = owm_env(instance="feat-789")  # TODO: wire up
    expected_keys = {
        "ODOO_BIN", "VENV_PYTHON", "PSQL", "DB_NAME", "DB_PORT",
        "INSTANCE_DIR", "LOG_FILE", "HTTP_PORT", "GEVENT_PORT",
        "ODOO_CONF", "WORKSPACE_DIR", "SCRIPTS_DIR", "WORKSPACE_SCRIPTS_DIR",
    }
    assert expected_keys.issubset(set(result.keys()))


# ---------------------------------------------------------------------------
# Workspace tools — owm_audit_log
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_audit_log_default_50_lines():
    result = owm_audit_log(n=50)  # TODO: wire up
    assert "lines" in result
    assert len(result["lines"]) <= 50


@pytest.mark.mcp_surface
def test_owm_audit_log_level_filter():
    result = owm_audit_log(n=100, level="ERROR")  # TODO: wire up
    for line in result["lines"]:
        assert line.get("level") in ("ERROR", "CRITICAL")


@pytest.mark.mcp_surface
def test_owm_audit_log_since_timestamp():
    result = owm_audit_log(since="2026-05-16T08:00:00")  # TODO: wire up
    assert "lines" in result
    for line in result["lines"]:
        assert line["timestamp"] >= "2026-05-16T08:00:00"


# ---------------------------------------------------------------------------
# Lifecycle tools — owm_new
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_new_returns_toml_path_and_content():
    result = owm_new(
        instance="feat-789",
        repos={"odoo": "19.0:shared", "product-core": "feat-789-dev:dev"},
    )  # TODO: wire up
    assert result["path"].endswith("instance.toml")
    assert result["content"] is not None
    assert "[repos]" in result["content"]


@pytest.mark.mcp_surface
def test_owm_new_already_exists_error():
    result = owm_new(instance="feat-789", repos={}, already_exists=True)  # TODO: wire up
    assert result == {"error": "instance already exists", "code": "ALREADY_EXISTS"}


# ---------------------------------------------------------------------------
# Lifecycle tools — owm_create
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_create_from_disk_returns_status_dict():
    result = owm_create(instance="feat-789")  # TODO: wire up
    assert result["status"] == "ok"
    assert "created" in result
    assert "updated" in result
    assert "skipped" in result


@pytest.mark.mcp_surface
def test_owm_create_inline_toml_no_disk_roundtrip():
    result = owm_create(instance="feat-789", toml="[repos]\nodoo = '19.0:shared'\n[database]\nname='feat'\npg_port=5432\n[server]\nhttp_port=8142\ngevent_port=8143\n")  # TODO: wire up
    assert result["status"] == "ok"


@pytest.mark.mcp_surface
def test_owm_create_branch_not_found_with_exists_flag():
    result = owm_create(
        instance="feat-789",
        repos={"product-core": "feat-789-dev:dev+exists"},
        simulate_branch_missing=True,
    )  # TODO: wire up
    assert result == {"error": "branch feat-789-dev not found on origin", "code": "BRANCH_NOT_FOUND"}


@pytest.mark.mcp_surface
def test_owm_create_dirty_worktree_error():
    result = owm_create(instance="feat-789", simulate_dirty_repo="product-core")  # TODO: wire up
    assert result["code"] == "DIRTY_WORKTREE"
    assert result["repo"] == "product-core"


# ---------------------------------------------------------------------------
# Lifecycle tools — owm_start / stop / kill / restart
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_start_returns_spawned():
    result = owm_start(instance="feat-789")  # TODO: wire up
    assert result["status"] == "spawned"
    assert result["pid"] is not None
    assert result["url"] == "https://feat-789.localhost"


@pytest.mark.mcp_surface
def test_owm_start_wait_healthy():
    result = owm_start(instance="feat-789", wait=True, simulate_healthy=True)  # TODO: wire up
    assert result["status"] == "healthy"


@pytest.mark.mcp_surface
def test_owm_start_wait_timeout():
    result = owm_start(instance="feat-789", wait=True, simulate_timeout=True)  # TODO: wire up
    assert result["code"] == "START_TIMEOUT"
    assert result["pid"] is not None


@pytest.mark.mcp_surface
def test_owm_start_already_running():
    result = owm_start(instance="feat-789", already_running=True, pid=1234)  # TODO: wire up
    assert result["status"] == "already_running"
    assert result["pid"] == 1234


@pytest.mark.mcp_surface
def test_owm_stop_returns_stopping():
    result = owm_stop(instance="feat-789", running=True, pid=1234)  # TODO: wire up
    assert result["status"] == "stopping"
    assert result["pid"] == 1234


@pytest.mark.mcp_surface
def test_owm_stop_wait_clean_exit():
    result = owm_stop(instance="feat-789", wait=True, simulate_clean_exit=True)  # TODO: wire up
    assert result["status"] == "stopped"


@pytest.mark.mcp_surface
def test_owm_stop_wait_timeout_never_kills():
    result = owm_stop(instance="feat-789", wait=True, simulate_timeout=True)  # TODO: wire up
    assert result["status"] == "timeout"
    assert result["code"] == "STOP_TIMEOUT"
    assert "kill" in result["hint"].lower()


@pytest.mark.mcp_surface
def test_owm_stop_not_running():
    result = owm_stop(instance="feat-789", running=False)  # TODO: wire up
    assert result == {"status": "not_running"}


@pytest.mark.mcp_surface
def test_owm_kill_running():
    result = owm_kill(instance="feat-789", running=True, pid=1234)  # TODO: wire up
    assert result == {"status": "killed", "pid": 1234}


@pytest.mark.mcp_surface
def test_owm_kill_not_running():
    result = owm_kill(instance="feat-789", running=False)  # TODO: wire up
    assert result == {"status": "not_running"}


@pytest.mark.mcp_surface
def test_owm_restart_returns_new_pid():
    result = owm_restart(instance="feat-789", wait=False, new_pid=1235)  # TODO: wire up
    assert result["status"] == "restarted"
    assert result["pid"] == 1235
    assert result["url"] == "https://feat-789.localhost"


@pytest.mark.mcp_surface
def test_owm_restart_stop_timeout_returns_error():
    result = owm_restart(instance="feat-789", simulate_stop_timeout=True)  # TODO: wire up
    assert result["code"] == "STOP_TIMEOUT"
    assert "kill" in result["hint"].lower()


# ---------------------------------------------------------------------------
# Lifecycle tools — owm_health
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_health_healthy():
    result = owm_health(instance="feat-789", pid=1234, http_alive=True)  # TODO: wire up
    assert result == {"status": "healthy", "pid": 1234, "http_alive": True, "url": "https://feat-789.localhost"}


@pytest.mark.mcp_surface
def test_owm_health_stopped():
    result = owm_health(instance="feat-789", process_running=False)  # TODO: wire up
    assert result == {"status": "stopped"}


@pytest.mark.mcp_surface
def test_owm_health_unmanaged():
    result = owm_health(instance="feat-789", unmanaged=True, pid=9999, port=8142)  # TODO: wire up
    assert result["status"] == "unmanaged"
    assert result["pid"] == 9999
    assert result["port"] == 8142


# ---------------------------------------------------------------------------
# Lifecycle tools — archive / delete / rename
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_archive_stopped_instance():
    result = owm_archive(instance="feat-789")  # TODO: wire up
    assert result == {"status": "archived", "path": "_archive/feat-789/"}


@pytest.mark.mcp_surface
def test_owm_archive_running_instance_error():
    result = owm_archive(instance="feat-789", running=True)  # TODO: wire up
    assert result == {"error": "stop instance first", "code": "INSTANCE_RUNNING"}


@pytest.mark.mcp_surface
def test_owm_archive_discard_db():
    result = owm_archive(instance="feat-789", discard_db=True)  # TODO: wire up
    assert result["status"] == "archived"


@pytest.mark.mcp_surface
def test_owm_delete_force_required_for_agents():
    result = owm_delete(instance="feat-789", force=True)  # TODO: wire up
    assert result == {"status": "deleted"}


@pytest.mark.mcp_surface
def test_owm_delete_running_error():
    result = owm_delete(instance="feat-789", force=True, running=True)  # TODO: wire up
    assert result == {"error": "stop instance first", "code": "INSTANCE_RUNNING"}


@pytest.mark.mcp_surface
def test_owm_rename_stopped_instance():
    result = owm_rename(instance="feat-789", new_name="pd-789")  # TODO: wire up
    assert result == {"status": "renamed", "old": "feat-789", "new": "pd-789", "url": "https://pd-789.localhost"}


@pytest.mark.mcp_surface
def test_owm_rename_running_error():
    result = owm_rename(instance="feat-789", new_name="pd-789", running=True)  # TODO: wire up
    assert result["code"] == "INSTANCE_RUNNING"


# ---------------------------------------------------------------------------
# Sync tools — owm_fetch / owm_sync / owm_push / owm_reset
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_fetch_returns_repo_and_worktree_status():
    result = owm_fetch()  # TODO: wire up
    assert "repos" in result
    assert "shared_worktrees" in result


@pytest.mark.mcp_surface
def test_owm_sync_fast_forward():
    result = owm_sync(
        instance="feat-789",
        simulate_repo_states={"product-core": "behind", "customer-config": "diverged", "odoo": "shared"},
    )  # TODO: wire up
    assert result["repos"]["product-core"]["status"] == "fast-forwarded"
    assert result["repos"]["customer-config"]["status"] == "diverged"
    assert result["repos"]["odoo"]["status"] == "skipped"


@pytest.mark.mcp_surface
def test_owm_sync_rebase():
    result = owm_sync(
        instance="feat-789",
        repo="customer-config",
        rebase=True,
        simulate_repo_states={"customer-config": "diverged"},
    )  # TODO: wire up
    assert result["repos"]["customer-config"]["status"] == "rebased"


@pytest.mark.mcp_surface
def test_owm_sync_dirty_skipped():
    result = owm_sync(
        instance="feat-789",
        repo="product-core",
        simulate_repo_states={"product-core": "dirty"},
    )  # TODO: wire up
    assert result["repos"]["product-core"]["status"] == "skipped"
    assert "uncommitted" in result["repos"]["product-core"]["reason"].lower()


@pytest.mark.mcp_surface
def test_owm_push_owned_branch():
    result = owm_push(instance="feat-789", repo="product-core")  # TODO: wire up
    assert result == {"status": "pushed", "repo": "product-core", "branch": "feat-789-dev"}


@pytest.mark.mcp_surface
def test_owm_push_diverged_error():
    result = owm_push(instance="feat-789", repo="product-core", simulate_diverged=True)  # TODO: wire up
    assert result["code"] == "DIVERGED"


@pytest.mark.mcp_surface
def test_owm_push_shared_error_with_hint():
    result = owm_push(instance="feat-789", repo="odoo")  # TODO: wire up
    assert result["code"] == "SHARED_REPO"
    assert "git" in result["hint"]


@pytest.mark.mcp_surface
def test_owm_push_not_owned_error():
    result = owm_push(instance="review-101", repo="product-core")  # TODO: wire up
    assert result["code"] == "NOT_OWNED"


@pytest.mark.mcp_surface
def test_owm_reset_clean():
    result = owm_reset(instance="review-101", repo="product-core")  # TODO: wire up
    assert result["status"] == "reset"
    assert result["to"].startswith("origin/")


@pytest.mark.mcp_surface
def test_owm_reset_dirty_requires_force():
    result = owm_reset(instance="review-101", repo="product-core", simulate_dirty=True)  # TODO: wire up
    assert result["code"] == "DIRTY_WORKTREE"
    assert "force" in result["hint"].lower()


@pytest.mark.mcp_surface
def test_owm_reset_force_discards():
    result = owm_reset(instance="review-101", repo="product-core", force=True, simulate_dirty=True)  # TODO: wire up
    assert result["status"] == "reset"
    assert result["discarded_changes"] is True


# ---------------------------------------------------------------------------
# Script tools — owm_run_script
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_run_script_ok_result():
    result = owm_run_script(
        instance="feat-789",
        script="run",
        simulate_summary={"ok": 8, "fail": 0, "warn": 0, "none": 2, "total": 10},
    )  # TODO: wire up
    assert result["status"] == "ok"
    assert result["summary"] == {"ok": 8, "fail": 0, "warn": 0, "none": 2, "total": 10}
    assert result["failures"] == []
    assert result["ndjson_path"] is not None


@pytest.mark.mcp_surface
def test_owm_run_script_fail_result_includes_failures():
    result = owm_run_script(
        instance="feat-789",
        script="run",
        simulate_summary={"ok": 7, "fail": 1, "warn": 0, "none": 2, "total": 10},
        simulate_failures=[{"case": "test_x", "status": "FAIL", "result": "error", "expected": "ok"}],
    )  # TODO: wire up
    assert result["status"] == "fail"
    assert len(result["failures"]) == 1
    assert result["failures"][0]["case"] == "test_x"


@pytest.mark.mcp_surface
def test_owm_run_script_abort_includes_rows_run_and_reason():
    result = owm_run_script(
        instance="feat-789",
        script="run",
        simulate_abort={"reason": "DB connection failed", "rows_run": 3},
    )  # TODO: wire up
    assert result["status"] == "abort"
    assert result["reason"] == "DB connection failed"
    assert result["rows_run"] == 3
    assert result["ndjson_path"] is not None


@pytest.mark.mcp_surface
def test_owm_run_script_full_stdout_not_returned():
    """Only failures surfaced; full stdout goes to ndjson file only."""
    result = owm_run_script(
        instance="feat-789",
        script="run",
        simulate_summary={"ok": 10, "fail": 0, "warn": 0, "none": 0, "total": 10},
    )  # TODO: wire up
    assert "stdout" not in result
    assert "full_output" not in result


@pytest.mark.mcp_surface
def test_owm_get_script_failures():
    result = owm_get_script_failures(ndjson_path="_dumps/feat-789/run-2026-05-16.ndjson")  # TODO: wire up
    assert isinstance(result, list)
    if result:
        assert "case" in result[0]
        assert "status" in result[0]


# ---------------------------------------------------------------------------
# Script tools — owm_compare
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_compare_ok_result():
    result = owm_compare(
        instance="feat-789",
        simulate_result="ok",
        simulate_summary={"identical": 9, "expected_changes": 0, "unexpected_changes": 0, "total": 9},
    )  # TODO: wire up
    assert result["status"] == "ok"
    assert result["unexpected"] == []


@pytest.mark.mcp_surface
def test_owm_compare_has_unexpected_changes():
    result = owm_compare(
        instance="feat-789",
        simulate_unexpected=[{"case": "test_x", "base": "OK", "feat": "FAIL", "result_diff": "..."}],
    )  # TODO: wire up
    assert result["status"] == "unexpected_changes"
    assert len(result["unexpected"]) == 1


@pytest.mark.mcp_surface
def test_owm_compare_no_compare_pair_configured():
    result = owm_compare(instance="feat-789", simulate_no_pair=True)  # TODO: wire up
    assert result["code"] == "NO_COMPARE_TARGET"
    assert "hint" in result


@pytest.mark.mcp_surface
def test_owm_compare_ad_hoc_base():
    result = owm_compare(instance="feat-789", base="main")  # TODO: wire up
    assert result["status"] in ("ok", "has_changes", "unexpected_changes", "abort")


# ---------------------------------------------------------------------------
# Script tools — owm_upgrade
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_upgrade_ok():
    result = owm_upgrade(instance="feat-789", modules=["my_module"])  # TODO: wire up
    assert result["status"] == "ok"
    assert result["modules"] == ["my_module"]
    assert result["restarted"] is True


@pytest.mark.mcp_surface
def test_owm_upgrade_fail_includes_log_tail():
    result = owm_upgrade(instance="feat-789", modules=["my_module"], simulate_failure=True)  # TODO: wire up
    assert result["status"] == "fail"
    assert result["code"] == "UPGRADE_FAILED"
    assert result["log_tail"] is not None


@pytest.mark.mcp_surface
def test_owm_upgrade_in_place_requires_workers():
    result = owm_upgrade(instance="feat-789", modules=["my_module"], in_place=True, workers=0)  # TODO: wire up
    assert result["code"] == "NO_WORKERS"


# ---------------------------------------------------------------------------
# DB tools
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_db_reset():
    result = owm_db_reset(instance="feat-789")  # TODO: wire up
    assert result["status"] == "ok"
    assert result["restored_from"] is not None


@pytest.mark.mcp_surface
def test_owm_db_dump_default_path():
    result = owm_db_dump(instance="feat-789")  # TODO: wire up
    assert result["status"] == "ok"
    assert "_dumps/feat-789/" in result["path"]


@pytest.mark.mcp_surface
def test_owm_db_dump_explicit_path():
    result = owm_db_dump(instance="feat-789", out="/explicit/path/snapshot.dump")  # TODO: wire up
    assert result["path"] == "/explicit/path/snapshot.dump"


@pytest.mark.mcp_surface
def test_owm_db_restore_relative_path():
    result = owm_db_restore(instance="feat-789", path="2026-05-16T09:32.dump")  # TODO: wire up
    assert result["status"] == "ok"


@pytest.mark.mcp_surface
def test_owm_db_restore_running_error():
    result = owm_db_restore(instance="feat-789", path="snap.dump", running=True)  # TODO: wire up
    assert result == {"error": "stop instance first", "code": "INSTANCE_RUNNING"}


# ---------------------------------------------------------------------------
# Context tools — owm_logs
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_logs_default():
    result = owm_logs(instance="feat-789", n=50)  # TODO: wire up
    assert "lines" in result
    assert "log_path" in result
    assert len(result["lines"]) <= 50


@pytest.mark.mcp_surface
def test_owm_logs_level_filter():
    result = owm_logs(instance="feat-789", n=200, level="ERROR")  # TODO: wire up
    assert "lines" in result


@pytest.mark.mcp_surface
def test_owm_logs_no_search_parameter():
    """owm_logs has no search/filter param; LOG_FILE path is returned for grep."""
    result = owm_logs(instance="feat-789", n=50)  # TODO: wire up
    assert "log_path" in result
    # no search param in signature — spec explicitly defers to LOG_FILE + grep


# ---------------------------------------------------------------------------
# Context tools — owm_agent_context
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_agent_context_with_role():
    result = owm_agent_context(instance="feat-789", role="reviewer")  # TODO: wire up
    assert "context" in result
    assert "sources" in result
    assert result["sources"]["role_template"] is not None
    assert result["sources"]["workspace"] is not None
    assert result["sources"]["instance"] is not None


@pytest.mark.mcp_surface
def test_owm_agent_context_no_role():
    result = owm_agent_context(instance="feat-789")  # TODO: wire up
    assert "context" in result
    assert result["sources"].get("role_template") is None


@pytest.mark.mcp_surface
def test_owm_agent_context_no_instance_notes_not_an_error():
    result = owm_agent_context(instance="feat-789", has_instance_notes=False)  # TODO: wire up
    assert "context" in result
    assert result["sources"]["instance"] is None


# ---------------------------------------------------------------------------
# Safety invariants
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
@pytest.mark.safety_invariants
def test_push_always_refuses_shared_repo():
    result = owm_push(instance="feat-789", repo="odoo")  # TODO: wire up
    assert result["code"] == "SHARED_REPO"


@pytest.mark.mcp_surface
@pytest.mark.safety_invariants
def test_push_always_refuses_unowned_branch():
    result = owm_push(instance="review-101", repo="product-core")  # TODO: wire up
    assert result["code"] == "NOT_OWNED"


@pytest.mark.mcp_surface
@pytest.mark.safety_invariants
def test_delete_operates_on_local_state_only():
    """delete removes local artefacts; no force-push or remote branch delete."""
    result = owm_delete(instance="feat-789", force=True)  # TODO: wire up
    assert result.get("remote_branches_deleted", []) == []
    assert result.get("force_pushed", False) is False


@pytest.mark.mcp_surface
@pytest.mark.safety_invariants
def test_archive_operates_on_local_state_only():
    result = owm_archive(instance="feat-789")  # TODO: wire up
    assert result.get("remote_branches_deleted", []) == []


@pytest.mark.mcp_surface
@pytest.mark.safety_invariants
def test_reset_operates_on_local_state_only():
    result = owm_reset(instance="review-101", repo="product-core")  # TODO: wire up
    assert result.get("remote_reset", False) is False


# === SPEC GAPS ===
# test_owm_adopt_mcp_tool: spec notes "owm adopt (CLI specced; MCP tool not listed)" in
#   Deferred section — no MCP surface for adopt tested here as it is intentionally absent.
# test_owm_ps_instant_implementation: "no git calls, no config parsing — instant" is a
#   performance invariant; no way to assert timing in a unit test without mocking.
# test_owm_compare_parallel_vs_sequential: owm_compare flags --parallel and --sequential
#   are specced at CLI level; MCP equivalent not shown in spec.
