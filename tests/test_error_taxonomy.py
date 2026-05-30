"""
Tests for consistent error code taxonomy across all MCP tools.
Covers: Error taxonomy section.

Each MCP tool returns errors as {"error": "<message>", "code": "<CODE>"}.
This file validates: (a) that code constants exist, (b) that the shape is
consistent, and (c) that specific operations produce the right code.
These complement the per-section tests; they assert the cross-cutting contract.
"""
import pytest
from unittest.mock import patch

from owm.errors import (
    NOT_FOUND, ALREADY_EXISTS, INSTANCE_RUNNING, DIRTY_WORKTREE,
    BRANCH_NOT_FOUND, NOT_OWNED, SHARED_REPO, DIVERGED,
    NO_COMPARE_TARGET, START_TIMEOUT, STOP_TIMEOUT,
    DB_UNAVAILABLE, UPGRADE_FAILED, XMLRPC_UNAVAILABLE,
    NO_WORKERS, PORT_RANGE_EXHAUSTED, PORT_CONTESTED,
)
from owm.errors import OwmError, format_error
from owm.mcp import (
    owm_status, owm_new, owm_delete, owm_archive, owm_rename,
    owm_db_restore, owm_create, owm_reset, owm_push, owm_compare,
    owm_start, owm_stop, owm_upgrade,
)
from owm.instance import StopResult
from owm.ports import assign_port, honour_pinned_port


# ---------------------------------------------------------------------------
# Error response shape
# ---------------------------------------------------------------------------

@pytest.mark.error_taxonomy
def test_error_response_has_error_and_code_keys():
    result = format_error(message="instance not found", code=NOT_FOUND)
    assert "error" in result
    assert "code" in result


@pytest.mark.error_taxonomy
def test_error_response_code_is_string():
    result = format_error(message="instance not found", code=NOT_FOUND)
    assert isinstance(result["code"], str)


@pytest.mark.error_taxonomy
def test_error_response_no_extra_required_keys():
    """Base error shape is just {error, code}; extra keys (hint, repo, etc.) are optional."""
    result = format_error(message="instance not found", code=NOT_FOUND)
    assert set(result.keys()) >= {"error", "code"}


# ---------------------------------------------------------------------------
# Code constants exist and are uppercase strings
#
# permanently_green: these tests verify static properties of the ErrorCode
# enum (well-formed values, no collisions). They were green before any
# implementation and must stay green throughout.
#
# TODO(rework): currently validates the enum definition itself. A stronger
# version would use AST/import analysis to assert that every OwmError raise
# site passes a valid ErrorCode member rather than a raw string — enforcing
# the convention at call sites, not just at declaration. Needs static analysis
# infrastructure (e.g. a custom pytest plugin or ruff rule) that doesn't
# exist yet.
# ---------------------------------------------------------------------------

@pytest.mark.error_taxonomy
@pytest.mark.permanently_green
def test_all_codes_are_uppercase_strings():
    codes = [
        NOT_FOUND, ALREADY_EXISTS, INSTANCE_RUNNING, DIRTY_WORKTREE,
        BRANCH_NOT_FOUND, NOT_OWNED, SHARED_REPO, DIVERGED,
        NO_COMPARE_TARGET, START_TIMEOUT, STOP_TIMEOUT,
        DB_UNAVAILABLE, UPGRADE_FAILED, XMLRPC_UNAVAILABLE,
        NO_WORKERS, PORT_RANGE_EXHAUSTED, PORT_CONTESTED,
    ]
    for code in codes:
        assert isinstance(code, str)
        assert code == code.upper()


@pytest.mark.error_taxonomy
@pytest.mark.permanently_green
def test_all_codes_are_distinct():
    codes = [
        NOT_FOUND, ALREADY_EXISTS, INSTANCE_RUNNING, DIRTY_WORKTREE,
        BRANCH_NOT_FOUND, NOT_OWNED, SHARED_REPO, DIVERGED,
        NO_COMPARE_TARGET, START_TIMEOUT, STOP_TIMEOUT,
        DB_UNAVAILABLE, UPGRADE_FAILED, XMLRPC_UNAVAILABLE,
        NO_WORKERS, PORT_RANGE_EXHAUSTED, PORT_CONTESTED,
    ]
    assert len(codes) == len(set(codes))


# ---------------------------------------------------------------------------
# Code semantics — each code maps to the right scenario
# ---------------------------------------------------------------------------

@pytest.mark.error_taxonomy
def test_not_found_for_missing_instance():
    result = owm_status(instance="nonexistent")
    assert result["code"] == NOT_FOUND


@pytest.mark.error_taxonomy
def test_already_exists_on_duplicate_new():
    with patch("owm.mcp.new_instance", side_effect=OwmError("already exists", code=ALREADY_EXISTS)):
        result = owm_new(instance="feat-789", repos={})
    assert result["code"] == ALREADY_EXISTS


@pytest.mark.error_taxonomy
def test_instance_running_on_delete_while_running():
    result = owm_delete(instance="feat-789", force=True, running=True)
    assert result["code"] == INSTANCE_RUNNING


@pytest.mark.error_taxonomy
def test_instance_running_on_archive_while_running():
    result = owm_archive(instance="feat-789", running=True)
    assert result["code"] == INSTANCE_RUNNING


@pytest.mark.error_taxonomy
def test_instance_running_on_rename_while_running():
    result = owm_rename(instance="feat-789", new_name="pd-789", running=True)
    assert result["code"] == INSTANCE_RUNNING


@pytest.mark.error_taxonomy
def test_instance_running_on_db_restore_while_running():
    result = owm_db_restore(instance="feat-789", path="snap.dump", running=True)
    assert result["code"] == INSTANCE_RUNNING


@pytest.mark.error_taxonomy
def test_dirty_worktree_on_create_branch_switch(standard_instance_toml, tmp_workspace):
    with patch("owm.mcp.read_repo_state", return_value={"status": "dirty"}):
        result = owm_create(instance="feat-789", workspace_root=str(tmp_workspace))
    assert result["code"] == DIRTY_WORKTREE


@pytest.mark.error_taxonomy
def test_dirty_worktree_on_reset_without_force(standard_instance_toml, tmp_workspace):
    with patch("owm.mcp.read_repo_state", return_value={"status": "dirty"}), \
         patch("owm.mcp.has_local_commits", return_value=False):
        result = owm_reset(instance="feat-789", repo="product_core",
                           workspace_root=str(tmp_workspace))
    assert result["code"] == DIRTY_WORKTREE


@pytest.mark.error_taxonomy
def test_branch_not_found_on_create_with_exists_flag(tmp_workspace):
    with patch("owm.mcp.branch_exists_on_origin", return_value=False):
        result = owm_create(
            instance="feat-789",
            repos={"product-core": "feat-789-dev:dev+exists"},
            workspace_root=str(tmp_workspace),
        )
    assert result["code"] == BRANCH_NOT_FOUND


@pytest.mark.error_taxonomy
def test_not_owned_on_push_readonly(tmp_workspace):
    inst_dir = tmp_workspace / "instances" / "review-101"
    inst_dir.mkdir(parents=True)
    (inst_dir / "instance.toml").write_text(
        '[repos]\nproduct_core = {branch = "feat-789-dev", base = "main", readonly = true}\n\n'
        '[database]\nname = "test"\npg_port = 5432\n\n'
        '[server]\nhttp_port = 8100\ngevent_port = 8101\n'
    )
    with patch("owm.mcp.read_repo_state", return_value={"status": "ahead"}):
        result = owm_push(instance="review-101", repo="product_core",
                          workspace_root=str(tmp_workspace))
    assert result["code"] == NOT_OWNED


@pytest.mark.error_taxonomy
def test_shared_repo_on_push_shared(standard_instance_toml, tmp_workspace):
    with patch("owm.mcp.read_repo_state", return_value={"status": "ahead"}):
        result = owm_push(instance="feat-789", repo="odoo_like",
                          workspace_root=str(tmp_workspace))
    assert result["code"] == SHARED_REPO


@pytest.mark.error_taxonomy
def test_shared_repo_error_includes_hint(standard_instance_toml, tmp_workspace):
    """SHARED_REPO errors must include a raw git command hint."""
    with patch("owm.mcp.read_repo_state", return_value={"status": "ahead"}):
        result = owm_push(instance="feat-789", repo="odoo_like",
                          workspace_root=str(tmp_workspace))
    assert result["code"] == SHARED_REPO
    assert "hint" in result
    assert "git" in result["hint"]


@pytest.mark.error_taxonomy
def test_diverged_on_push_diverged_branch(standard_instance_toml, tmp_workspace):
    with patch("owm.mcp.read_repo_state", return_value={"status": "diverged"}):
        result = owm_push(instance="feat-789", repo="product_core",
                          workspace_root=str(tmp_workspace))
    assert result["code"] == DIVERGED


@pytest.mark.error_taxonomy
def test_no_compare_target_when_no_pair_and_no_base(tmp_workspace):
    (tmp_workspace / "workspace.toml").write_text(
        '[repos]\nproduct_core = "url"\n\n[clusters]\n"19" = {pg_version = "16", port = 5432}\n'
    )
    result = owm_compare(instance="feat-789", workspace_root=str(tmp_workspace))
    assert result["code"] == NO_COMPARE_TARGET
    assert "hint" in result


@pytest.mark.error_taxonomy
def test_start_timeout_code():
    with patch("owm.mcp.start_instance",
               side_effect=OwmError("timed out", code=START_TIMEOUT, pid=1234)):
        result = owm_start(instance="feat-789", wait=True)
    assert result["code"] == START_TIMEOUT


@pytest.mark.error_taxonomy
def test_stop_timeout_code_and_hint():
    with patch("owm.mcp.stop_instance", return_value=StopResult(
        status="stop_timeout",
        force_killed=False,
        hint="run owm kill to force-stop the instance",
    )):
        result = owm_stop(instance="feat-789", wait=True)
    assert result["code"] == STOP_TIMEOUT
    assert "kill" in result["hint"].lower()


@pytest.mark.error_taxonomy
def test_upgrade_failed_includes_log_tail():
    result = owm_upgrade(instance="feat-789", modules=["my_module"], simulate_failure=True)
    assert result["code"] == UPGRADE_FAILED
    assert "log_tail" in result


@pytest.mark.error_taxonomy
def test_no_workers_on_in_place_upgrade_without_workers():
    result = owm_upgrade(instance="feat-789", modules=["my_module"], in_place=True, workers=0)
    assert result["code"] == NO_WORKERS


@pytest.mark.error_taxonomy
def test_port_exhausted_when_range_full():
    with pytest.raises(Exception) as exc_info:
        assign_port(pool={"range": [8100, 8299], "occupied": set(range(8100, 8300))})
    assert PORT_RANGE_EXHAUSTED in str(exc_info.value)


@pytest.mark.error_taxonomy
def test_port_contested_when_running_instance_holds_pinned_port():
    with pytest.raises(Exception) as exc_info:
        honour_pinned_port(
            pinned_http=8143,
            occupied={8143},
            existing_instances=[{"instance": "review-101", "running": True, "http_port": 8143}],
        )
    assert PORT_CONTESTED in str(exc_info.value)


# === SPEC GAPS ===
# test_db_unavailable_trigger: DB_UNAVAILABLE is defined but no MCP tool example is shown
#   that produces it; it's implied by create/start when pg_isready fails but the exact
#   tool and response shape is not demonstrated in the spec.
# test_xmlrpc_unavailable_trigger: XMLRPC_UNAVAILABLE is shown for owm_upgrade in_place
#   but the condition (instance running but xmlrpc endpoint not responding) is not
#   elaborated beyond the code definition.
