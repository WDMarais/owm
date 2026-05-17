"""
Tests for consistent error code taxonomy across all MCP tools.
Covers: Error taxonomy section.

Each MCP tool returns errors as {"error": "<message>", "code": "<CODE>"}.
This file validates: (a) that code constants exist, (b) that the shape is
consistent, and (c) that specific operations produce the right code.
These complement the per-section tests; they assert the cross-cutting contract.
"""
import pytest

from owm.errors import (
    NOT_FOUND, ALREADY_EXISTS, INSTANCE_RUNNING, DIRTY_WORKTREE,
    BRANCH_NOT_FOUND, NOT_OWNED, SHARED_REPO, DIVERGED,
    NO_COMPARE_TARGET, START_TIMEOUT, STOP_TIMEOUT,
    DB_UNAVAILABLE, UPGRADE_FAILED, XMLRPC_UNAVAILABLE,
    NO_WORKERS, PORT_EXHAUSTED, PORT_CONTESTED,
)
from owm.errors import OwmError, format_error


# ---------------------------------------------------------------------------
# Error response shape
# ---------------------------------------------------------------------------

@pytest.mark.error_taxonomy
def test_error_response_has_error_and_code_keys():
    result = format_error(message="instance not found", code=NOT_FOUND)  # TODO: wire up
    assert "error" in result
    assert "code" in result


@pytest.mark.error_taxonomy
def test_error_response_code_is_string():
    result = format_error(message="instance not found", code=NOT_FOUND)  # TODO: wire up
    assert isinstance(result["code"], str)


@pytest.mark.error_taxonomy
def test_error_response_no_extra_required_keys():
    """Base error shape is just {error, code}; extra keys (hint, repo, etc.) are optional."""
    result = format_error(message="instance not found", code=NOT_FOUND)  # TODO: wire up
    assert set(result.keys()) >= {"error", "code"}


# ---------------------------------------------------------------------------
# Code constants exist and are uppercase strings
# ---------------------------------------------------------------------------

@pytest.mark.error_taxonomy
def test_all_codes_are_uppercase_strings():
    codes = [
        NOT_FOUND, ALREADY_EXISTS, INSTANCE_RUNNING, DIRTY_WORKTREE,
        BRANCH_NOT_FOUND, NOT_OWNED, SHARED_REPO, DIVERGED,
        NO_COMPARE_TARGET, START_TIMEOUT, STOP_TIMEOUT,
        DB_UNAVAILABLE, UPGRADE_FAILED, XMLRPC_UNAVAILABLE,
        NO_WORKERS, PORT_EXHAUSTED, PORT_CONTESTED,
    ]
    for code in codes:
        assert isinstance(code, str)
        assert code == code.upper()


@pytest.mark.error_taxonomy
def test_all_codes_are_distinct():
    codes = [
        NOT_FOUND, ALREADY_EXISTS, INSTANCE_RUNNING, DIRTY_WORKTREE,
        BRANCH_NOT_FOUND, NOT_OWNED, SHARED_REPO, DIVERGED,
        NO_COMPARE_TARGET, START_TIMEOUT, STOP_TIMEOUT,
        DB_UNAVAILABLE, UPGRADE_FAILED, XMLRPC_UNAVAILABLE,
        NO_WORKERS, PORT_EXHAUSTED, PORT_CONTESTED,
    ]
    assert len(codes) == len(set(codes))


# ---------------------------------------------------------------------------
# Code semantics — each code maps to the right scenario
# ---------------------------------------------------------------------------

@pytest.mark.error_taxonomy
def test_not_found_for_missing_instance():
    # owm_status(instance="nonexistent") → NOT_FOUND
    # TODO: from owm.mcp import owm_status
    def owm_status(*args, **kwargs):
        raise NotImplementedError
    result = owm_status(instance="nonexistent")  # TODO: wire up
    assert result["code"] == NOT_FOUND


@pytest.mark.error_taxonomy
def test_already_exists_on_duplicate_new():
    # owm_new(instance already exists) → ALREADY_EXISTS
    # TODO: from owm.mcp import owm_new
    def owm_new(*args, **kwargs):
        raise NotImplementedError
    result = owm_new(instance="feat-789", repos={}, already_exists=True)  # TODO: wire up
    assert result["code"] == ALREADY_EXISTS


@pytest.mark.error_taxonomy
def test_instance_running_on_delete_while_running():
    # TODO: from owm.mcp import owm_delete
    def owm_delete(*args, **kwargs):
        raise NotImplementedError
    result = owm_delete(instance="feat-789", force=True, running=True)  # TODO: wire up
    assert result["code"] == INSTANCE_RUNNING


@pytest.mark.error_taxonomy
def test_instance_running_on_archive_while_running():
    # TODO: from owm.mcp import owm_archive
    def owm_archive(*args, **kwargs):
        raise NotImplementedError
    result = owm_archive(instance="feat-789", running=True)  # TODO: wire up
    assert result["code"] == INSTANCE_RUNNING


@pytest.mark.error_taxonomy
def test_instance_running_on_rename_while_running():
    # TODO: from owm.mcp import owm_rename
    def owm_rename(*args, **kwargs):
        raise NotImplementedError
    result = owm_rename(instance="feat-789", new_name="pd-789", running=True)  # TODO: wire up
    assert result["code"] == INSTANCE_RUNNING


@pytest.mark.error_taxonomy
def test_instance_running_on_db_restore_while_running():
    # TODO: from owm.mcp import owm_db_restore
    def owm_db_restore(*args, **kwargs):
        raise NotImplementedError
    result = owm_db_restore(instance="feat-789", path="snap.dump", running=True)  # TODO: wire up
    assert result["code"] == INSTANCE_RUNNING


@pytest.mark.error_taxonomy
def test_dirty_worktree_on_create_branch_switch():
    # TODO: from owm.mcp import owm_create
    def owm_create(*args, **kwargs):
        raise NotImplementedError
    result = owm_create(instance="feat-789", simulate_dirty_repo="product-core")  # TODO: wire up
    assert result["code"] == DIRTY_WORKTREE


@pytest.mark.error_taxonomy
def test_dirty_worktree_on_reset_without_force():
    # TODO: from owm.mcp import owm_reset
    def owm_reset(*args, **kwargs):
        raise NotImplementedError
    result = owm_reset(instance="review-101", repo="product-core", simulate_dirty=True)  # TODO: wire up
    assert result["code"] == DIRTY_WORKTREE


@pytest.mark.error_taxonomy
def test_branch_not_found_on_create_with_exists_flag():
    # TODO: from owm.mcp import owm_create
    def owm_create(*args, **kwargs):
        raise NotImplementedError
    result = owm_create(
        instance="feat-789",
        repos={"product-core": "feat-789-dev:dev+exists"},
        simulate_branch_missing=True,
    )  # TODO: wire up
    assert result["code"] == BRANCH_NOT_FOUND


@pytest.mark.error_taxonomy
def test_not_owned_on_push_readonly():
    # TODO: from owm.mcp import owm_push
    def owm_push(*args, **kwargs):
        raise NotImplementedError
    result = owm_push(instance="review-101", repo="product-core")  # TODO: wire up
    assert result["code"] == NOT_OWNED


@pytest.mark.error_taxonomy
def test_shared_repo_on_push_shared():
    # TODO: from owm.mcp import owm_push
    def owm_push(*args, **kwargs):
        raise NotImplementedError
    result = owm_push(instance="feat-789", repo="odoo")  # TODO: wire up
    assert result["code"] == SHARED_REPO


@pytest.mark.error_taxonomy
def test_shared_repo_error_includes_hint():
    """SHARED_REPO errors must include a raw git command hint."""
    # TODO: from owm.mcp import owm_push
    def owm_push(*args, **kwargs):
        raise NotImplementedError
    result = owm_push(instance="feat-789", repo="odoo")  # TODO: wire up
    assert result["code"] == SHARED_REPO
    assert "hint" in result
    assert "git" in result["hint"]


@pytest.mark.error_taxonomy
def test_diverged_on_push_diverged_branch():
    # TODO: from owm.mcp import owm_push
    def owm_push(*args, **kwargs):
        raise NotImplementedError
    result = owm_push(instance="feat-789", repo="product-core", simulate_diverged=True)  # TODO: wire up
    assert result["code"] == DIVERGED


@pytest.mark.error_taxonomy
def test_no_compare_target_when_no_pair_and_no_base():
    # TODO: from owm.mcp import owm_compare
    def owm_compare(*args, **kwargs):
        raise NotImplementedError
    result = owm_compare(instance="feat-789", simulate_no_pair=True)  # TODO: wire up
    assert result["code"] == NO_COMPARE_TARGET
    assert "hint" in result


@pytest.mark.error_taxonomy
def test_start_timeout_code():
    # TODO: from owm.mcp import owm_start
    def owm_start(*args, **kwargs):
        raise NotImplementedError
    result = owm_start(instance="feat-789", wait=True, simulate_timeout=True)  # TODO: wire up
    assert result["code"] == START_TIMEOUT


@pytest.mark.error_taxonomy
def test_stop_timeout_code_and_hint():
    # TODO: from owm.mcp import owm_stop
    def owm_stop(*args, **kwargs):
        raise NotImplementedError
    result = owm_stop(instance="feat-789", wait=True, simulate_timeout=True)  # TODO: wire up
    assert result["code"] == STOP_TIMEOUT
    assert "kill" in result["hint"].lower()


@pytest.mark.error_taxonomy
def test_upgrade_failed_includes_log_tail():
    # TODO: from owm.mcp import owm_upgrade
    def owm_upgrade(*args, **kwargs):
        raise NotImplementedError
    result = owm_upgrade(instance="feat-789", modules=["my_module"], simulate_failure=True)  # TODO: wire up
    assert result["code"] == UPGRADE_FAILED
    assert "log_tail" in result


@pytest.mark.error_taxonomy
def test_no_workers_on_in_place_upgrade_without_workers():
    # TODO: from owm.mcp import owm_upgrade
    def owm_upgrade(*args, **kwargs):
        raise NotImplementedError
    result = owm_upgrade(instance="feat-789", modules=["my_module"], in_place=True, workers=0)  # TODO: wire up
    assert result["code"] == NO_WORKERS


@pytest.mark.error_taxonomy
def test_port_exhausted_when_range_full():
    # TODO: from owm.ports import assign_port
    def assign_port(*args, **kwargs):
        raise NotImplementedError
    with pytest.raises(Exception) as exc_info:
        assign_port(pool={"range": [8100, 8299], "occupied": set(range(8100, 8300))})  # TODO: wire up
    assert PORT_EXHAUSTED in str(exc_info.value)


@pytest.mark.error_taxonomy
def test_port_contested_when_running_instance_holds_pinned_port():
    # TODO: from owm.ports import honour_pinned_port
    def honour_pinned_port(*args, **kwargs):
        raise NotImplementedError
    with pytest.raises(Exception) as exc_info:
        honour_pinned_port(
            pinned_http=8143,
            occupied={8143},
            existing_instances=[{"instance": "review-101", "running": True, "http_port": 8143}],
        )  # TODO: wire up
    assert PORT_CONTESTED in str(exc_info.value)


# === SPEC GAPS ===
# test_db_unavailable_trigger: DB_UNAVAILABLE is defined but no MCP tool example is shown
#   that produces it; it's implied by create/start when pg_isready fails but the exact
#   tool and response shape is not demonstrated in the spec.
# test_xmlrpc_unavailable_trigger: XMLRPC_UNAVAILABLE is shown for owm_upgrade in_place
#   but the condition (instance running but xmlrpc endpoint not responding) is not
#   elaborated beyond the code definition.
