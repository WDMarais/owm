"""
Tests for fetch, sync, push, reset, and confirmed-working checkpoints.
Covers: Fetch and sync section.
"""
import pytest

from owm.sync import fetch_workspace, sync_instance, push_instance
from owm.sync import reset_instance, record_checkpoint, rollback_to_checkpoint


# ---------------------------------------------------------------------------
# owm fetch — workspace-wide
# ---------------------------------------------------------------------------

@pytest.mark.fetch_sync
def test_fetch_fetches_repos_with_updates_in_parallel():
    result = fetch_workspace(
        repos=["odoo", "product-core", "customer-config"],
        repos_with_updates=["odoo", "product-core"],
    )  # TODO: wire up
    assert "odoo" in result.fetched
    assert "product-core" in result.fetched
    assert result.skipped == ["customer-config"]


@pytest.mark.fetch_sync
def test_fetch_fast_forwards_shared_worktrees():
    result = fetch_workspace(
        repos=["odoo"],
        repos_with_updates=["odoo"],
        shared_worktrees={"odoo/19.0": {"branch": "19.0"}},
    )  # TODO: wire up
    assert "odoo/19.0" in result.shared_worktrees_fast_forwarded


@pytest.mark.fetch_sync
def test_fetch_logs_previous_hash_before_fast_forward():
    result = fetch_workspace(
        repos=["odoo"],
        repos_with_updates=["odoo"],
        shared_worktrees={"odoo/19.0": {"branch": "19.0", "current_hash": "abc123"}},
    )  # TODO: wire up
    assert result.shared_worktree_hashes_logged["odoo/19.0"] == "abc123"


@pytest.mark.fetch_sync
def test_fetch_emits_fetch_completed_event():
    result = fetch_workspace(repos=["odoo"], repos_with_updates=[])  # TODO: wire up
    assert "fetch_completed" in result.events_emitted


@pytest.mark.fetch_sync
def test_fetch_unreachable_repo_warns_and_continues():
    result = fetch_workspace(
        repos=["odoo", "product-core"],
        repos_with_updates=["odoo"],
        unreachable_repos=["product-core"],
    )  # TODO: wire up
    assert "product-core" in result.warnings
    assert "odoo" in result.fetched


@pytest.mark.fetch_sync
def test_fetch_shared_worktree_with_local_commits_hard_stops_that_worktree():
    result = fetch_workspace(
        repos=["odoo"],
        repos_with_updates=["odoo"],
        shared_worktrees={"odoo/19.0": {"branch": "19.0", "has_local_commits": True}},
    )  # TODO: wire up
    assert "odoo/19.0" in result.blocked_worktrees
    assert result.blocked_worktrees["odoo/19.0"]["reason"] == "local_commits"


@pytest.mark.fetch_sync
def test_fetch_db_snapshot_before_migration_fast_forward():
    """Fetch introduces DB migration on fast-forward → DB snapshot taken first."""
    result = fetch_workspace(
        repos=["odoo"],
        repos_with_updates=["odoo"],
        shared_worktrees={"odoo/19.0": {"branch": "19.0", "has_migration": True}},
        instances_on_shared=["feat-789"],
    )  # TODO: wire up
    assert result.db_snapshots_taken != []


# ---------------------------------------------------------------------------
# owm sync
# ---------------------------------------------------------------------------

@pytest.mark.fetch_sync
def test_sync_fast_forwards_when_purely_behind():
    result = sync_instance(
        instance="feat-789",
        repo_states={"product-core": {"status": "behind", "behind_by": 3}},
    )  # TODO: wire up
    assert result["product-core"]["status"] == "fast-forwarded"
    assert result["product-core"]["from"] is not None
    assert result["product-core"]["to"] is not None


@pytest.mark.fetch_sync
def test_sync_surfaces_divergence_and_instructs_rebase():
    result = sync_instance(
        instance="feat-789",
        repo_states={"customer-config": {"status": "diverged"}},
    )  # TODO: wire up
    assert result["customer-config"]["status"] == "diverged"
    assert "rebase" in result["customer-config"]["hint"].lower()


@pytest.mark.fetch_sync
def test_sync_rebase_resolves_divergence():
    result = sync_instance(
        instance="feat-789",
        repo_states={"customer-config": {"status": "diverged"}},
        rebase=True,
        repo="customer-config",
    )  # TODO: wire up
    assert result["customer-config"]["status"] == "rebased"


@pytest.mark.fetch_sync
def test_sync_skips_dirty_repo_with_reason():
    result = sync_instance(
        instance="feat-789",
        repo_states={"product-core": {"status": "dirty"}},
    )  # TODO: wire up
    assert result["product-core"]["status"] == "skipped"
    assert "uncommitted" in result["product-core"]["reason"].lower()


@pytest.mark.fetch_sync
def test_sync_skips_shared_worktree():
    result = sync_instance(
        instance="feat-789",
        repo_states={"odoo": {"status": "behind", "shared": True}},
    )  # TODO: wire up
    assert result["odoo"]["status"] == "skipped"
    assert "shared" in result["odoo"]["reason"].lower()


# ---------------------------------------------------------------------------
# owm push
# ---------------------------------------------------------------------------

@pytest.mark.fetch_sync
def test_push_owned_branch_ahead_of_origin():
    result = push_instance(
        instance="feat-789",
        repo="product-core",
        branch_status="ahead",
        owned=True,
        shared=False,
    )  # TODO: wire up
    assert result["status"] == "pushed"
    assert result["repo"] == "product-core"


@pytest.mark.fetch_sync
def test_push_diverged_branch_refused():
    with pytest.raises(Exception) as exc_info:
        push_instance(
            instance="feat-789",
            repo="product-core",
            branch_status="diverged",
            owned=True,
            shared=False,
        )  # TODO: wire up
    assert "DIVERGED" in str(exc_info.value)


@pytest.mark.fetch_sync
def test_push_unowned_branch_refused():
    with pytest.raises(Exception) as exc_info:
        push_instance(
            instance="review-101",
            repo="product-core",
            branch_status="ahead",
            owned=False,
            shared=False,
        )  # TODO: wire up
    assert "NOT_OWNED" in str(exc_info.value)


@pytest.mark.fetch_sync
def test_push_shared_branch_refused_with_git_hint():
    with pytest.raises(Exception) as exc_info:
        push_instance(
            instance="feat-789",
            repo="odoo",
            branch="19.0",
            branch_status="ahead",
            owned=False,
            shared=True,
        )  # TODO: wire up
    err = str(exc_info.value)
    assert "SHARED_REPO" in err
    assert "git" in err and "push" in err


@pytest.mark.fetch_sync
def test_push_all_pushes_owned_skips_shared():
    result = push_instance(
        instance="feat-789",
        all_repos=True,
        repo_states={
            "product-core": {"owned": True, "shared": False, "status": "ahead"},
            "odoo":          {"owned": False, "shared": True},
        },
    )  # TODO: wire up
    assert result["product-core"]["status"] == "pushed"
    assert result["odoo"]["status"] == "skipped"
    assert "shared" in result["odoo"]["reason"].lower()


# ---------------------------------------------------------------------------
# owm reset
# ---------------------------------------------------------------------------

@pytest.mark.fetch_sync
def test_reset_hard_resets_worktrees_to_origin():
    result = reset_instance(
        instance="review-101",
        repo="product-core",
        dirty=False,
    )  # TODO: wire up
    assert result["status"] == "reset"
    assert result["to"].startswith("origin/")


@pytest.mark.fetch_sync
def test_reset_warns_about_local_commits():
    result = reset_instance(
        instance="review-101",
        repo="product-core",
        dirty=False,
        has_local_commits=True,
    )  # TODO: wire up
    assert result["warning"] is not None
    assert "local commits" in result["warning"].lower() or "origin" in result["warning"].lower()


@pytest.mark.fetch_sync
def test_reset_dirty_worktree_requires_force():
    with pytest.raises(Exception) as exc_info:
        reset_instance(
            instance="review-101",
            repo="product-core",
            dirty=True,
            force=False,
        )  # TODO: wire up
    assert "DIRTY_WORKTREE" in str(exc_info.value)


@pytest.mark.fetch_sync
def test_reset_force_discards_changes():
    result = reset_instance(
        instance="review-101",
        repo="product-core",
        dirty=True,
        force=True,
    )  # TODO: wire up
    assert result["status"] == "reset"
    assert result["discarded_changes"] is True


@pytest.mark.fetch_sync
def test_reset_skips_shared_worktrees():
    result = reset_instance(
        instance="review-101",
        all_repos=True,
        repo_states={"odoo": {"shared": True}, "product-core": {"shared": False, "dirty": False}},
    )  # TODO: wire up
    assert result["odoo"]["status"] == "skipped"
    assert "shared" in result["odoo"]["reason"].lower()


# ---------------------------------------------------------------------------
# Confirmed-working checkpoints
# ---------------------------------------------------------------------------

@pytest.mark.fetch_sync
def test_checkpoint_recorded_when_all_checks_pass():
    result = record_checkpoint(
        instance="feat-789",
        repo_hashes={"product-core": "abc123", "customer-config": "def456"},
        db_snapshot_path="_dumps/feat-789/cp-2026-05-16.dump",
        manual=False,
    )  # TODO: wire up
    assert result.timestamp is not None
    assert result.hashes == {"product-core": "abc123", "customer-config": "def456"}
    assert result.db_snapshot == "_dumps/feat-789/cp-2026-05-16.dump"
    assert result.manual is False


@pytest.mark.fetch_sync
def test_manual_checkpoint_marked_as_manual():
    result = record_checkpoint(
        instance="feat-789",
        repo_hashes={"product-core": "abc123"},
        db_snapshot_path="_dumps/feat-789/cp-2026-05-16.dump",
        manual=True,
        note="integration tests green",
    )  # TODO: wire up
    assert result.manual is True
    assert result.note == "integration tests green"


@pytest.mark.fetch_sync
def test_rollback_reverts_worktrees_and_db():
    result = rollback_to_checkpoint(
        instance="feat-789",
        checkpoint={"hashes": {"product-core": "abc123"}, "db_snapshot": "_dumps/feat-789/cp.dump"},
    )  # TODO: wire up
    assert result.worktrees_reverted is True
    assert result.db_restored is True
    assert result.checkpoint_used is not None


@pytest.mark.fetch_sync
def test_rollback_surfaces_what_changed_since_checkpoint():
    result = rollback_to_checkpoint(
        instance="feat-789",
        checkpoint={"hashes": {"product-core": "abc123"}, "db_snapshot": "_dumps/feat-789/cp.dump"},
        current_hashes={"product-core": "xyz789"},
    )  # TODO: wire up
    assert result.changes_since is not None


# === SPEC GAPS ===
# test_fetch_smart_skip_implementation: spec says "smart skip if nothing new" — it is
#   unclear whether this is implemented as ls-remote comparison, timestamp check, or
#   pack file inspection.
# test_checkpoint_auto_trigger_conditions: spec says "green script run + health check
#   passing + module install check passing" — the exact conditions for auto-checkpoint
#   and whether all three must pass simultaneously is not fully specced.
# test_rollback_cli_surface: rollback concept is specced in this section but CLI and MCP
#   surfaces are listed as deferred in the Deferred section.
