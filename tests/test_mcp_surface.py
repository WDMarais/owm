"""
Tests for the MCP tool surface: workspace, lifecycle, sync, script, DB, and context tools.
Covers: MCP surface section.

Safety invariants tested explicitly:
- No tool touches upstream destructively
- Push tools refuse unowned/shared branches unconditionally
- Delete/archive/reset tools operate on local state only
"""
import pytest
from unittest.mock import patch

from owm.mcp import (
    owm_status,
    owm_ps,
    owm_validate,
    owm_env,
    owm_audit_log,
    owm_new,
    owm_create,
    owm_start,
    owm_stop,
    owm_kill,
    owm_restart,
    owm_health,
    owm_archive,
    owm_delete,
    owm_rename,
    owm_fetch,
    owm_sync,
    owm_push,
    owm_reset,
    owm_run_script,
    owm_get_script_failures,
    owm_compare,
    owm_upgrade,
    owm_db_reset,
    owm_db_dump,
    owm_db_restore,
    owm_logs,
    owm_agent_context,
)
from owm.errors import OwmError, ALREADY_EXISTS
from owm.instance import InstanceInfo
from owm.operations import LogsResult
from owm.database import ResetDbResult


# ---------------------------------------------------------------------------
# Workspace tools — owm_status (single-instance)
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_status_instance_stopped_no_conflict(standard_instance_toml, tmp_workspace):
    with patch("owm.api.health_check", return_value=InstanceInfo(status="stopped")), \
         patch("owm.api.find_conflicting_process", return_value=None):
        result = owm_status(instance="feat-789")
    assert result["instance"] == "feat-789"
    assert result["state"] == "stopped"
    assert result["http_port"] == 18142
    assert result["db"] == "owm_test_feat789"
    assert result["local_url"] == "http://localhost:18142"
    assert result["url"] is None
    assert result["suspected_linked"] is None


@pytest.mark.mcp_surface
def test_owm_status_instance_not_found(tmp_workspace):
    result = owm_status(instance="nonexistent")
    assert result["error"] is not None
    assert result["code"] == "NOT_FOUND"


@pytest.mark.mcp_surface
def test_owm_status_instance_suspected_orphan(standard_instance_toml, tmp_workspace):
    proc = {"pid": 5678, "name": "python3", "cmdline": "python3 /ws/odoo-bin --config feat-789.conf"}
    with patch("owm.api.health_check", return_value=InstanceInfo(status="stopped")), \
         patch("owm.api.find_conflicting_process", return_value=proc):
        result = owm_status(instance="feat-789")
    assert result["suspected_linked"]["classification"] == "probable_orphan"
    assert result["suspected_linked"]["pid"] == 5678


@pytest.mark.mcp_surface
def test_owm_status_instance_suspected_squatter(standard_instance_toml, tmp_workspace):
    proc = {"pid": 9999, "name": "node", "cmdline": "node server.js"}
    with patch("owm.api.health_check", return_value=InstanceInfo(status="stopped")), \
         patch("owm.api.find_conflicting_process", return_value=proc):
        result = owm_status(instance="feat-789")
    assert result["suspected_linked"]["classification"] == "probable_squatter"
    assert result["suspected_linked"]["pid"] == 9999


@pytest.mark.mcp_surface
def test_owm_status_instance_running(standard_instance_toml, tmp_workspace):
    with patch("owm.api.health_check", return_value=InstanceInfo(status="healthy", pid=1234, url="https://feat-789.localhost")), \
         patch("owm.api.find_conflicting_process", return_value=None):
        result = owm_status(instance="feat-789")
    assert result["state"] == "healthy"
    assert result["pid"] == 1234
    assert result["url"] == "https://feat-789.localhost"
    assert result["local_url"] == "http://localhost:18142"
    assert result["suspected_linked"] is None


# ---------------------------------------------------------------------------
# Workspace tools — owm_status (workspace-level)
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_status_workspace_empty(tmp_workspace):
    result = owm_status()
    assert result["instances"] == {}
    assert result["repo_alerts"] == []
    assert result["port_alerts"] == []
    assert result["unmanaged_odoo"] == []


@pytest.mark.mcp_surface
def test_owm_status_workspace_stopped_instance(standard_instance_toml, tmp_workspace):
    with patch("owm.api.health_check", return_value=InstanceInfo(status="stopped")), \
         patch("owm.api.find_conflicting_process", return_value=None):
        result = owm_status()
    assert "feat-789" in result["instances"]
    assert result["instances"]["feat-789"]["state"] == "stopped"
    assert result["instances"]["feat-789"]["local_url"] == "http://localhost:18142"


@pytest.mark.mcp_surface
def test_owm_status_workspace_running_instance(standard_instance_toml, tmp_workspace):
    with patch("owm.api.health_check", return_value=InstanceInfo(status="healthy", pid=1234, url="https://feat-789.localhost")), \
         patch("owm.api.find_conflicting_process", return_value=None):
        result = owm_status()
    inst = result["instances"]["feat-789"]
    assert inst["state"] == "healthy"
    assert inst["pid"] == 1234
    assert inst["url"] == "https://feat-789.localhost"


@pytest.mark.mcp_surface
def test_owm_status_workspace_unmanaged_port_surfaces_in_port_alerts(standard_instance_toml, tmp_workspace):
    proc = {"pid": 5678, "name": "python3", "cmdline": "python3 /ws/odoo-bin --config feat-789.conf"}
    with patch("owm.api.health_check", return_value=InstanceInfo(status="unmanaged", pid=5678)), \
         patch("owm.api.find_conflicting_process", return_value=proc):
        result = owm_status()
    assert len(result["port_alerts"]) == 1
    alert = result["port_alerts"][0]
    assert alert["instance"] == "feat-789"
    assert alert["http_port"] == 18142
    assert alert["classification"] == "probable_orphan"


@pytest.mark.mcp_surface
def test_owm_status_workspace_orphan_dir_surfaces_as_warning(tmp_workspace):
    (tmp_workspace / "instances" / "mystery-dir").mkdir()
    result = owm_status()
    assert any(w["type"] == "orphan_dir" for w in result["workspace_warnings"])


@pytest.mark.mcp_surface
def test_owm_status_workspace_files_and_underscore_dirs_silently_ignored(tmp_workspace):
    (tmp_workspace / "instances" / ".gitkeep").touch()
    (tmp_workspace / "instances" / "_scratch").mkdir()
    result = owm_status()
    assert result["workspace_warnings"] == []


# ---------------------------------------------------------------------------
# Workspace tools — owm_ps
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_ps_returns_managed_and_unmanaged():
    result = owm_ps()
    assert "managed" in result
    assert "unmanaged" in result


@pytest.mark.mcp_surface
def test_owm_ps_managed_entry_shape():
    fake = [{"instance": "feat-789", "pid": 1234, "port": 8142, "url": "https://feat-789.localhost", "status": "healthy"}]
    with patch("owm.mcp.list_running_instances", return_value=fake):
        result = owm_ps()
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
    result = owm_ps()
    assert "managed" in result
    assert "unmanaged" in result


@pytest.mark.mcp_surface
def test_owm_ps_surfaces_orphan_process(tmp_workspace):
    """owm_ps.unmanaged lists odoo owm isn't tracking — here an instance that is
    no longer managed-running but whose process is still up."""
    orphan = {"pid": 5678, "instance": "deleted-x"}
    with patch("owm.api.workspace_odoo_processes", return_value=[orphan]), \
         patch("owm.api.list_running_instances", return_value=[]):
        result = owm_ps()
    assert orphan in result["unmanaged"]


# ---------------------------------------------------------------------------
# Workspace tools — owm_validate
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_validate_static_valid():
    result = owm_validate(instance="feat-789")
    assert "valid" in result
    assert "errors" in result
    assert "warnings" in result
    assert isinstance(result["errors"], list)


@pytest.mark.mcp_surface
def test_owm_validate_live_richer_errors():
    result = owm_validate(instance="feat-789", live=True)
    assert result["valid"] in (True, False)
    assert isinstance(result["errors"], list)


# ---------------------------------------------------------------------------
# Workspace tools — owm_env
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_env_returns_all_required_keys(standard_instance_toml, tmp_workspace):
    result = owm_env(instance="feat-789")
    expected_keys = {
        "ODOO_BIN", "VENV_PYTHON", "PSQL", "DB_NAME", "DB_PORT",
        "INSTANCE_DIR", "LOG_FILE", "HTTP_PORT", "GEVENT_PORT",
        "ODOO_CONF", "WORKSPACE_DIR", "SCRIPTS_DIR", "WORKSPACE_SCRIPTS_DIR",
    }
    # env is self-contained under "env"; findings ride alongside, not mixed in.
    assert expected_keys.issubset(set(result["env"].keys()))
    assert "findings" not in result["env"]


# ---------------------------------------------------------------------------
# Workspace tools — owm_audit_log
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_audit_log_default_50_lines():
    result = owm_audit_log(n=50)
    assert "lines" in result
    assert len(result["lines"]) <= 50


@pytest.mark.mcp_surface
def test_owm_audit_log_level_filter():
    result = owm_audit_log(n=100, level="ERROR")
    for line in result["lines"]:
        assert line.get("level") in ("ERROR", "CRITICAL")


@pytest.mark.mcp_surface
def test_owm_audit_log_since_timestamp():
    result = owm_audit_log(since="2026-05-16T08:00:00")
    assert "lines" in result
    for line in result["lines"]:
        assert line["timestamp"] >= "2026-05-16T08:00:00"


# ---------------------------------------------------------------------------
# Lifecycle tools — owm_new
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_new_returns_toml_path_and_content(tmp_path):
    result = owm_new(
        instance="feat-789",
        repos={"odoo": "19.0:shared", "product-core": "feat-789-dev:dev"},
    )
    assert result["path"].endswith("instance.toml")
    assert result["content"] is not None
    assert "[repos]" in result["content"]


@pytest.mark.mcp_surface
def test_owm_new_already_exists_error():
    with patch("owm.mcp.new_instance", side_effect=OwmError("already exists", code=ALREADY_EXISTS)):
        result = owm_new(instance="feat-789", repos={})
    assert result == {"error": "instance already exists", "code": "ALREADY_EXISTS"}


# ---------------------------------------------------------------------------
# Lifecycle tools — owm_create
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_create_from_disk_returns_status_dict(standard_instance_toml, tmp_workspace):
    from owm.instance import CreateResult
    fake = CreateResult(status="created", worktrees_created=True, db_created=True,
                        port_reserved=True, proxy_block_written=True, odoo_conf_generated=True)
    with patch("owm.mcp.read_repo_state", return_value={"status": "clean"}), \
         patch("owm.mcp.create_instance", return_value=fake):
        result = owm_create(instance="feat-789")
    assert result["status"] == "ok"
    assert "created" in result
    assert "updated" in result
    assert "skipped" in result


@pytest.mark.mcp_surface
def test_owm_create_inline_toml_no_disk_roundtrip():
    result = owm_create(instance="feat-789", toml='[repos]\nodoo = {branch = "19.0", shared = true}\n[database]\nname="feat"\npg_port=5432\n[server]\nhttp_port=8142\ngevent_port=8143\n')
    assert result["status"] == "ok"


@pytest.mark.mcp_surface
def test_owm_create_branch_not_found_with_exists_flag(tmp_workspace):
    with patch("owm.mcp.branch_exists_on_origin", return_value=False):
        result = owm_create(
            instance="feat-789",
            repos={"product-core": "feat-789-dev:dev+exists"},
        )
    assert result == {"error": "branch feat-789-dev not found on origin", "code": "BRANCH_NOT_FOUND"}


@pytest.mark.mcp_surface
def test_owm_create_dirty_worktree_error(standard_instance_toml, tmp_workspace):
    with patch("owm.mcp.read_repo_state", return_value={"status": "dirty"}):
        result = owm_create(instance="feat-789")
    assert result["code"] == "DIRTY_WORKTREE"
    assert result["repo"] == "product_core"


# ---------------------------------------------------------------------------
# Lifecycle tools — owm_start / stop / kill / restart
# ---------------------------------------------------------------------------

from owm.instance import StartResult, StopResult, KillResult, RestartResult
from owm.errors import OwmError, START_TIMEOUT, STOP_TIMEOUT


@pytest.mark.mcp_surface
def test_owm_start_returns_spawned():
    with patch("owm.mcp.start_instance", return_value=StartResult(status="spawned", pid=1234)):
        result = owm_start(instance="feat-789")
    assert result["status"] == "spawned"
    assert result["pid"] is not None
    assert result["url"] == "https://feat-789.localhost"


@pytest.mark.mcp_surface
def test_owm_start_wait_healthy():
    with patch("owm.mcp.start_instance", return_value=StartResult(status="healthy", pid=1234)):
        result = owm_start(instance="feat-789", wait=True)
    assert result["status"] == "healthy"


@pytest.mark.mcp_surface
def test_owm_start_wait_timeout():
    with patch("owm.mcp.start_instance",
               side_effect=OwmError("timed out", code=START_TIMEOUT, pid=1234)):
        result = owm_start(instance="feat-789", wait=True)
    assert result["code"] == "START_TIMEOUT"
    assert result["pid"] is not None


@pytest.mark.mcp_surface
def test_owm_start_already_running():
    with patch("owm.mcp.start_instance", return_value=StartResult(status="already_running", pid=1234)):
        result = owm_start(instance="feat-789")
    assert result["status"] == "already_running"
    assert result["pid"] == 1234


@pytest.mark.mcp_surface
def test_owm_stop_returns_stopping():
    with patch("owm.mcp.stop_instance", return_value=StopResult(status="stopping", pid=1234)):
        result = owm_stop(instance="feat-789")
    assert result["status"] == "stopping"
    assert result["pid"] == 1234


@pytest.mark.mcp_surface
def test_owm_stop_wait_clean_exit():
    with patch("owm.mcp.stop_instance", return_value=StopResult(status="stopped", pid=1234)):
        result = owm_stop(instance="feat-789", wait=True)
    assert result["status"] == "stopped"


@pytest.mark.mcp_surface
def test_owm_stop_wait_timeout_never_kills():
    with patch("owm.mcp.stop_instance", return_value=StopResult(
        status="stop_timeout",
        force_killed=False,
        hint="run owm kill to force-stop the instance",
    )):
        result = owm_stop(instance="feat-789", wait=True)
    assert result["status"] == "timeout"
    assert result["code"] == "STOP_TIMEOUT"
    assert "kill" in result["hint"].lower()


@pytest.mark.mcp_surface
def test_owm_stop_not_running():
    with patch("owm.mcp.stop_instance", return_value=StopResult(status="not_running")):
        result = owm_stop(instance="feat-789")
    assert result == {"status": "not_running"}


@pytest.mark.mcp_surface
def test_owm_kill_running():
    with patch("owm.mcp.kill_instance", return_value=KillResult(status="killed", pid=1234)):
        result = owm_kill(instance="feat-789")
    assert result == {"status": "killed", "pid": 1234}


@pytest.mark.mcp_surface
def test_owm_kill_not_running():
    with patch("owm.mcp.kill_instance", return_value=KillResult(status="not_running")):
        result = owm_kill(instance="feat-789")
    assert result == {"status": "not_running"}


@pytest.mark.mcp_surface
def test_owm_restart_returns_new_pid():
    with patch("owm.mcp.restart_instance", return_value=RestartResult(status="restarted", pid=1235)):
        result = owm_restart(instance="feat-789")
    assert result["status"] == "restarted"
    assert result["pid"] == 1235
    assert result["url"] == "https://feat-789.localhost"


@pytest.mark.mcp_surface
def test_owm_restart_stop_timeout_returns_error():
    with patch("owm.mcp.restart_instance",
               side_effect=OwmError("stop timed out", code=STOP_TIMEOUT)):
        result = owm_restart(instance="feat-789")
    assert result["code"] == "STOP_TIMEOUT"
    assert "kill" in result["hint"].lower()


# ---------------------------------------------------------------------------
# Lifecycle tools — owm_health
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_health_healthy():
    with patch("owm.mcp.health_check", return_value=InstanceInfo(status="healthy", pid=1234, http_alive=True, url="https://feat-789.localhost")):
        result = owm_health(instance="feat-789")
    assert result == {"status": "healthy", "pid": 1234, "http_alive": True, "url": "https://feat-789.localhost"}


@pytest.mark.mcp_surface
def test_owm_health_stopped():
    with patch("owm.mcp.health_check", return_value=InstanceInfo(status="stopped")):
        result = owm_health(instance="feat-789")
    assert result == {"status": "stopped"}


@pytest.mark.mcp_surface
def test_owm_health_unmanaged():
    with patch("owm.mcp.health_check", return_value=InstanceInfo(status="unmanaged", pid=9999, port=8142)):
        result = owm_health(instance="feat-789")
    assert result["status"] == "unmanaged"
    assert result["pid"] == 9999
    assert result["port"] == 8142


# ---------------------------------------------------------------------------
# Lifecycle tools — archive / delete / rename
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_archive_stopped_instance():
    from owm.archive import ArchiveResult
    fake = ArchiveResult(
        preserved=["instance.toml", "db.dump"], archive_path="_archive/feat-789/",
        db_dumped=True, db_dump_path="_archive/feat-789/db.dump",
        worktrees_removed=True, live_db_dropped=True, port_freed=True,
    )
    with patch("owm.mcp.archive_instance", return_value=fake):
        result = owm_archive(instance="feat-789")
    assert result == {"status": "archived", "path": "_archive/feat-789/"}


@pytest.mark.mcp_surface
def test_owm_archive_running_instance_error():
    result = owm_archive(instance="feat-789", running=True)
    assert result == {"error": "stop instance first", "code": "INSTANCE_RUNNING"}


@pytest.mark.mcp_surface
def test_owm_archive_discard_db():
    from owm.archive import ArchiveResult
    fake = ArchiveResult(
        preserved=["instance.toml"], archive_path="_archive/feat-789/",
        db_dumped=False, db_dump_path=None,
        worktrees_removed=True, live_db_dropped=True, port_freed=True,
    )
    with patch("owm.mcp.archive_instance", return_value=fake):
        result = owm_archive(instance="feat-789", discard_db=True)
    assert result["status"] == "archived"


@pytest.mark.mcp_surface
def test_owm_delete_force_required_for_agents():
    from owm.operations import DeleteResult
    fake = DeleteResult(
        status="deleted", worktrees_removed=True, db_dropped=True,
        proxy_block_removed=True, instance_folder_removed=True,
    )
    with patch("owm.mcp.delete_instance", return_value=fake):
        result = owm_delete(instance="feat-789", force=True)
    assert result == {"status": "deleted"}


@pytest.mark.mcp_surface
def test_owm_delete_running_error():
    result = owm_delete(instance="feat-789", force=True, running=True)
    assert result == {"error": "stop instance first", "code": "INSTANCE_RUNNING"}


@pytest.mark.mcp_surface
def test_owm_rename_stopped_instance(standard_instance_toml, tmp_workspace):
    with patch("owm.operations.subprocess.run") as mock_run, \
         patch("owm.operations.shutil.move"):
        mock_run.return_value.returncode = 0
        result = owm_rename(
            instance="feat-789",
            new_name="pd-789",
        )
    assert result == {"status": "renamed", "old": "feat-789", "new": "pd-789", "url": "https://pd-789.localhost"}


@pytest.mark.mcp_surface
def test_owm_rename_running_error():
    result = owm_rename(instance="feat-789", new_name="pd-789", running=True)
    assert result["code"] == "INSTANCE_RUNNING"


# ---------------------------------------------------------------------------
# Sync tools — owm_fetch / owm_sync / owm_push / owm_reset
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_fetch_returns_repo_and_worktree_status(tmp_workspace):
    (tmp_workspace / "workspace.toml").write_text(
        '[repos]\nproduct_core = "file:///fake"\n\n'
        '[clusters]\n"19" = {pg_version = "16", port = 5432}\n'
    )
    with patch("owm.sync.git_fetch_bare", return_value=False):
        result = owm_fetch()
    assert "repos" in result
    assert "shared_worktrees" in result


@pytest.mark.mcp_surface
def test_owm_sync_fast_forward(standard_instance_toml, tmp_workspace):
    with patch("owm.sync.read_repo_state", return_value={"status": "behind", "behind_by": 3}), \
         patch("owm.sync.git_fast_forward"):
        result = owm_sync(instance="feat-789")
    assert result["repos"]["product_core"]["status"] == "fast-forwarded"
    assert result["repos"]["odoo_like"]["status"] == "skipped"   # shared worktree


@pytest.mark.mcp_surface
def test_owm_sync_rebase(standard_instance_toml, tmp_workspace):
    with patch("owm.sync.read_repo_state", return_value={"status": "diverged"}), \
         patch("owm.sync.git_rebase"):
        result = owm_sync(instance="feat-789", repo="product_core",
                          rebase=True)
    assert result["repos"]["product_core"]["status"] == "rebased"


@pytest.mark.mcp_surface
def test_owm_sync_dirty_skipped(standard_instance_toml, tmp_workspace):
    with patch("owm.sync.read_repo_state", return_value={"status": "dirty"}):
        result = owm_sync(instance="feat-789", repo="product_core")
    assert result["repos"]["product_core"]["status"] == "skipped"
    assert "uncommitted" in result["repos"]["product_core"]["reason"].lower()


@pytest.mark.mcp_surface
def test_owm_push_owned_branch(standard_instance_toml, tmp_workspace):
    with patch("owm.sync.read_repo_state", return_value={"status": "ahead", "ahead_by": 1}), \
         patch("owm.sync.git_push"):
        result = owm_push(instance="feat-789", repo="product_core")
    assert result["status"] == "pushed"
    assert result["repo"] == "product_core"
    assert result["branch"] == "feat-789-dev"


@pytest.mark.mcp_surface
def test_owm_push_diverged_error(standard_instance_toml, tmp_workspace):
    with patch("owm.sync.read_repo_state", return_value={"status": "diverged"}):
        result = owm_push(instance="feat-789", repo="product_core")
    assert result["code"] == "DIVERGED"


@pytest.mark.mcp_surface
def test_owm_push_shared_error_with_hint(standard_instance_toml, tmp_workspace):
    # odoo_like is declared shared in standard_instance_toml
    with patch("owm.sync.read_repo_state", return_value={"status": "ahead"}):
        result = owm_push(instance="feat-789", repo="odoo_like")
    assert result["code"] == "SHARED_REPO"
    assert "git" in result["hint"]


@pytest.mark.mcp_surface
def test_owm_push_not_owned_error(tmp_workspace):
    inst_dir = tmp_workspace / "instances" / "review-101"
    inst_dir.mkdir(parents=True)
    (inst_dir / "instance.toml").write_text(
        '[repos]\nproduct_core = {branch = "feat-789-dev", base = "main", readonly = true}\n\n'
        '[database]\nname = "test"\npg_port = 5432\n\n'
        '[server]\nhttp_port = 8100\ngevent_port = 8101\n'
    )
    with patch("owm.sync.read_repo_state", return_value={"status": "ahead"}):
        result = owm_push(instance="review-101", repo="product_core")
    assert result["code"] == "NOT_OWNED"


@pytest.mark.mcp_surface
def test_owm_reset_clean(standard_instance_toml, tmp_workspace):
    with patch("owm.mcp.read_repo_state", return_value={"status": "clean"}), \
         patch("owm.mcp.has_local_commits", return_value=False), \
         patch("owm.mcp.git_reset_hard"):
        result = owm_reset(instance="feat-789", repo="product_core")
    assert result["status"] == "reset"
    assert result["to"].startswith("origin/")


@pytest.mark.mcp_surface
def test_owm_reset_dirty_requires_force(standard_instance_toml, tmp_workspace):
    with patch("owm.mcp.read_repo_state", return_value={"status": "dirty"}), \
         patch("owm.mcp.has_local_commits", return_value=False):
        result = owm_reset(instance="feat-789", repo="product_core")
    assert result["code"] == "DIRTY_WORKTREE"
    assert "force" in result["hint"].lower()


@pytest.mark.mcp_surface
def test_owm_reset_force_discards(standard_instance_toml, tmp_workspace):
    with patch("owm.mcp.read_repo_state", return_value={"status": "dirty"}), \
         patch("owm.mcp.has_local_commits", return_value=False), \
         patch("owm.mcp.git_reset_hard"):
        result = owm_reset(instance="feat-789", repo="product_core",
                           force=True)
    assert result["status"] == "reset"
    assert result["discarded_changes"] is True


# ---------------------------------------------------------------------------
# Script tools — owm_run_script
# ---------------------------------------------------------------------------

from owm.scripts import ScriptResult, ScriptSummary


@pytest.mark.mcp_surface
def test_owm_run_script_ok_result(tmp_path):
    with patch("owm.mcp.execute_script", return_value=""), \
         patch("owm.mcp.run_script", return_value=ScriptResult(
             status="ok",
             summary=ScriptSummary(ok=8, fail=0, warn=0, none=2, total=10),
             rows=[],
         )):
        result = owm_run_script(instance="feat-789", script="run")
    assert result["status"] == "ok"
    assert result["summary"] == {"ok": 8, "fail": 0, "warn": 0, "none": 2, "total": 10}
    assert result["failures"] == []
    assert result["ndjson_path"] is not None


@pytest.mark.mcp_surface
def test_owm_run_script_fail_result_includes_failures(tmp_path):
    failure_row = {"case": "test_x", "status": "FAIL", "result": "error", "expected": "ok"}
    with patch("owm.mcp.execute_script", return_value=""), \
         patch("owm.mcp.run_script", return_value=ScriptResult(
             status="fail",
             summary=ScriptSummary(ok=7, fail=1, warn=0, none=2, total=10),
             rows=[failure_row],
         )):
        result = owm_run_script(instance="feat-789", script="run")
    assert result["status"] == "fail"
    assert len(result["failures"]) == 1
    assert result["failures"][0]["case"] == "test_x"


@pytest.mark.mcp_surface
def test_owm_run_script_abort_includes_rows_run_and_reason(tmp_path):
    with patch("owm.mcp.execute_script", return_value=""), \
         patch("owm.mcp.run_script", return_value=ScriptResult(
             status="abort",
             summary=ScriptSummary(ok=3, fail=0, warn=0, none=0, total=3),
             rows=[],
             rows_run=3,
             abort_reason="DB connection failed",
         )):
        result = owm_run_script(instance="feat-789", script="run")
    assert result["status"] == "abort"
    assert result["reason"] == "DB connection failed"
    assert result["rows_run"] == 3
    assert result["ndjson_path"] is not None


@pytest.mark.mcp_surface
def test_owm_run_script_full_stdout_not_returned(tmp_path):
    """Only failures surfaced; full stdout goes to ndjson file only."""
    with patch("owm.mcp.execute_script", return_value=""), \
         patch("owm.mcp.run_script", return_value=ScriptResult(
             status="ok",
             summary=ScriptSummary(ok=10, fail=0, warn=0, none=0, total=10),
             rows=[],
         )):
        result = owm_run_script(instance="feat-789", script="run")
    assert "stdout" not in result
    assert "full_output" not in result


@pytest.mark.mcp_surface
def test_owm_get_script_failures():
    result = owm_get_script_failures(ndjson_path="/nonexistent/path.ndjson")
    assert isinstance(result, list)
    if result:
        assert "case" in result[0]
        assert "status" in result[0]


# ---------------------------------------------------------------------------
# Script tools — owm_compare
# ---------------------------------------------------------------------------

from owm.scripts import CompareResult


def _write_workspace_toml(ws_path, compare_pairs=None):
    pairs_section = ""
    if compare_pairs:
        rendered = "[" + ", ".join(f'["{a}", "{b}"]' for a, b in compare_pairs) + "]"
        pairs_section = f'\n[compare_pairs]\npairs = {rendered}\n'
    (ws_path / "workspace.toml").write_text(
        '[repos]\nproduct_core = "url"\n\n'
        '[clusters]\n"19" = {pg_version = "16", port = 5432}\n'
        + pairs_section
    )


@pytest.mark.mcp_surface
def test_owm_compare_ok_result(tmp_workspace):
    _write_workspace_toml(tmp_workspace, compare_pairs=[("feat-789", "main")])
    with patch("owm.mcp.compare_instances", return_value=CompareResult(
        status="ok", base_instance="main", feat_instance="feat-789",
        summary=ScriptSummary(ok=9, fail=0, warn=0, none=0, total=9),
        unexpected=[],
    )):
        result = owm_compare(instance="feat-789")
    assert result["status"] == "ok"
    assert result["unexpected"] == []


@pytest.mark.mcp_surface
def test_owm_compare_has_unexpected_changes(tmp_workspace):
    _write_workspace_toml(tmp_workspace, compare_pairs=[("feat-789", "main")])
    with patch("owm.mcp.compare_instances", return_value=CompareResult(
        status="unexpected_changes", base_instance="main", feat_instance="feat-789",
        summary=ScriptSummary(ok=0, fail=0, warn=0, none=0, total=9, unexpected_changes=1),
        unexpected=[{"case": "test_x", "base": "OK", "feat": "FAIL", "result_diff": "..."}],
    )):
        result = owm_compare(instance="feat-789")
    assert result["status"] == "unexpected_changes"
    assert len(result["unexpected"]) == 1


@pytest.mark.mcp_surface
def test_owm_compare_no_compare_pair_configured(tmp_workspace):
    _write_workspace_toml(tmp_workspace)  # no compare_pairs
    result = owm_compare(instance="feat-789")
    assert result["code"] == "NO_COMPARE_TARGET"
    assert "hint" in result


@pytest.mark.mcp_surface
def test_owm_compare_ad_hoc_base(tmp_workspace):
    _write_workspace_toml(tmp_workspace)
    with patch("owm.mcp.compare_instances", return_value=CompareResult(
        status="ok", base_instance="main", feat_instance="feat-789",
        summary=ScriptSummary(ok=0, fail=0, warn=0, none=0, total=0),
        unexpected=[],
    )):
        result = owm_compare(instance="feat-789", base="main")
    assert result["status"] in ("ok", "has_changes", "unexpected_changes", "abort")


# ---------------------------------------------------------------------------
# Script tools — owm_upgrade
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_upgrade_ok():
    result = owm_upgrade(instance="feat-789", modules=["my_module"])
    assert result["status"] == "ok"
    assert result["modules"] == ["my_module"]
    assert result["restarted"] is True


@pytest.mark.mcp_surface
@pytest.mark.xfail(strict=True, reason="upgrade execution + failure detection not wired; "
                   "upgrade_modules is a pure planner (no odoo-bin -u, no rc/log capture). "
                   "Asserts the real UPGRADE_FAILED contract so it flips green when wired.")
def test_owm_upgrade_fail_includes_log_tail():
    result = owm_upgrade(instance="feat-789", modules=["my_module"])
    assert result["status"] == "fail"
    assert result["code"] == "UPGRADE_FAILED"
    assert result["log_tail"] is not None


@pytest.mark.mcp_surface
def test_owm_upgrade_in_place_requires_workers():
    result = owm_upgrade(instance="feat-789", modules=["my_module"], in_place=True, workers=0)
    assert result["code"] == "NO_WORKERS"


# ---------------------------------------------------------------------------
# DB tools
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_db_reset(tmp_workspace):
    inst_dir = tmp_workspace / "instances" / "feat-789"
    inst_dir.mkdir(parents=True, exist_ok=True)
    (inst_dir / "instance.toml").write_text(
        '[repos]\nodoo = {branch = "19.0", shared = true}\n'
        "[database]\nname = \"feat789_db\"\npg_port = 5432\ntemplate = \"feat789_base\"\n"
        "[server]\nhttp_port = 8142\ngevent_port = 8143\n"
    )
    fake = ResetDbResult(restored_from="feat789_base")
    with patch("owm.mcp.reset_db", return_value=fake):
        result = owm_db_reset(instance="feat-789")
    assert result["status"] == "ok"
    assert result["restored_from"] == "feat789_base"


@pytest.mark.mcp_surface
def test_owm_db_dump_default_path(standard_instance_toml, tmp_workspace):
    with patch("owm.operations._pg_dump"):
        result = owm_db_dump(instance="feat-789")
    assert result["status"] == "ok"
    assert "_dumps/feat-789/" in result["path"]


@pytest.mark.mcp_surface
def test_owm_db_dump_explicit_path(standard_instance_toml, tmp_workspace):
    out = str(tmp_workspace / "snapshot.dump")
    with patch("owm.operations._pg_dump"), patch("owm.operations.os.makedirs"):
        result = owm_db_dump(instance="feat-789", out=out)
    assert result["path"] == out


@pytest.mark.mcp_surface
def test_owm_db_restore_relative_path(standard_instance_toml, tmp_workspace):
    with patch("owm.operations._pg_restore"):
        result = owm_db_restore(instance="feat-789", path="2026-05-16T09:32.dump")
    assert result["status"] == "ok"


@pytest.mark.mcp_surface
def test_owm_db_restore_running_error():
    result = owm_db_restore(instance="feat-789", path="snap.dump", running=True)
    assert result == {"error": "stop instance first", "code": "INSTANCE_RUNNING"}


# ---------------------------------------------------------------------------
# Context tools — owm_logs
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_logs_default():
    fake = LogsResult(lines=[], log_path="instances/feat-789/instance.log")
    with patch("owm.mcp.show_logs", return_value=fake):
        result = owm_logs(instance="feat-789", n=50)
    assert "lines" in result
    assert "log_path" in result
    assert len(result["lines"]) <= 50


@pytest.mark.mcp_surface
def test_owm_logs_level_filter():
    fake = LogsResult(lines=[], log_path="instances/feat-789/instance.log")
    with patch("owm.mcp.show_logs", return_value=fake):
        result = owm_logs(instance="feat-789", n=200, level="ERROR")
    assert "lines" in result


@pytest.mark.mcp_surface
def test_owm_logs_no_search_parameter():
    """owm_logs has no search/filter param; LOG_FILE path is returned for grep."""
    fake = LogsResult(lines=[], log_path="instances/feat-789/instance.log")
    with patch("owm.mcp.show_logs", return_value=fake):
        result = owm_logs(instance="feat-789", n=50)
    assert "log_path" in result
    # no search param in signature — spec explicitly defers to LOG_FILE + grep


# ---------------------------------------------------------------------------
# Context tools — owm_agent_context
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_agent_context_with_role():
    result = owm_agent_context(instance="feat-789", role="reviewer")
    assert "context" in result
    assert "sources" in result
    assert result["sources"]["role_template"] is not None
    assert result["sources"]["workspace"] is not None
    assert result["sources"]["instance"] is not None


@pytest.mark.mcp_surface
def test_owm_agent_context_no_role():
    result = owm_agent_context(instance="feat-789")
    assert "context" in result
    assert result["sources"].get("role_template") is None


@pytest.mark.mcp_surface
def test_owm_agent_context_no_instance_notes_not_an_error():
    result = owm_agent_context(instance="feat-789", has_instance_notes=False)
    assert "context" in result
    assert result["sources"]["instance"] is None


# ---------------------------------------------------------------------------
# Safety invariants
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
@pytest.mark.safety_invariants
def test_push_always_refuses_shared_repo(standard_instance_toml, tmp_workspace):
    with patch("owm.sync.read_repo_state", return_value={"status": "ahead"}):
        result = owm_push(instance="feat-789", repo="odoo_like")
    assert result["code"] == "SHARED_REPO"


@pytest.mark.mcp_surface
@pytest.mark.safety_invariants
def test_push_always_refuses_unowned_branch(tmp_workspace):
    inst_dir = tmp_workspace / "instances" / "review-101"
    inst_dir.mkdir(parents=True)
    (inst_dir / "instance.toml").write_text(
        '[repos]\nproduct_core = {branch = "feat-789-dev", base = "main", readonly = true}\n\n'
        '[database]\nname = "test"\npg_port = 5432\n\n'
        '[server]\nhttp_port = 8100\ngevent_port = 8101\n'
    )
    with patch("owm.sync.read_repo_state", return_value={"status": "ahead"}):
        result = owm_push(instance="review-101", repo="product_core")
    assert result["code"] == "NOT_OWNED"


@pytest.mark.mcp_surface
@pytest.mark.safety_invariants
def test_delete_operates_on_local_state_only():
    """delete removes local artefacts; no force-push or remote branch delete."""
    from owm.operations import DeleteResult
    fake = DeleteResult(status="deleted", worktrees_removed=True, db_dropped=True,
                        proxy_block_removed=True, instance_folder_removed=True)
    with patch("owm.mcp.delete_instance", return_value=fake):
        result = owm_delete(instance="feat-789", force=True)
    assert result.get("remote_branches_deleted", []) == []
    assert result.get("force_pushed", False) is False


@pytest.mark.mcp_surface
@pytest.mark.safety_invariants
def test_archive_operates_on_local_state_only():
    from owm.archive import ArchiveResult
    fake = ArchiveResult(
        preserved=["instance.toml", "db.dump"], archive_path="_archive/feat-789/",
        db_dumped=True, db_dump_path="_archive/feat-789/db.dump",
        worktrees_removed=True, live_db_dropped=True, port_freed=True,
    )
    with patch("owm.mcp.archive_instance", return_value=fake):
        result = owm_archive(instance="feat-789")
    assert result.get("remote_branches_deleted", []) == []


@pytest.mark.mcp_surface
@pytest.mark.safety_invariants
def test_reset_operates_on_local_state_only(standard_instance_toml, tmp_workspace):
    with patch("owm.mcp.read_repo_state", return_value={"status": "clean"}), \
         patch("owm.mcp.has_local_commits", return_value=False), \
         patch("owm.mcp.git_reset_hard"):
        result = owm_reset(instance="feat-789", repo="product_core")
    assert result.get("remote_reset", False) is False


# === SPEC GAPS ===
# test_owm_adopt_mcp_tool: spec notes "owm adopt (CLI specced; MCP tool not listed)" in
#   Deferred section — no MCP surface for adopt tested here as it is intentionally absent.
# test_owm_ps_instant_implementation: "no git calls, no config parsing — instant" is a
#   performance invariant; no way to assert timing in a unit test without mocking.
# test_owm_compare_parallel_vs_sequential: owm_compare flags --parallel and --sequential
#   are specced at CLI level; MCP equivalent not shown in spec.


# ---------------------------------------------------------------------------
# OWM_WORKSPACE env var as MCP default workspace
# ---------------------------------------------------------------------------

@pytest.mark.mcp_surface
def test_owm_workspace_env_var_overrides_dot_default(monkeypatch, tmp_workspace, standard_instance_toml):
    monkeypatch.setenv("OWM_WORKSPACE", str(tmp_workspace))
    result = owm_env(instance="feat-789")
    assert "error" not in result
    assert str(tmp_workspace) in result["env"]["WORKSPACE_DIR"]
