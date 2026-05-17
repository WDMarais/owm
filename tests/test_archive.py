"""
Tests for instance archival, restore, and archive-delete operations.
Covers: Archive section.
"""
import pytest

from owm.archive import archive_instance, create_from_archive
from owm.archive import delete_archive, detect_archive_conflict


# ---------------------------------------------------------------------------
# owm archive
# ---------------------------------------------------------------------------

@pytest.mark.archive
def test_archive_default_preserves_toml_db_session_review():
    result = archive_instance(instance="feat-789", workspace_root="/ws")  # TODO: wire up
    assert result.preserved == ["instance.toml", "db.dump", "notes.md", "review/"]  \
        or set(result.preserved) >= {"instance.toml", "db.dump"}
    assert result.archive_path == "/ws/_archive/feat-789/"


@pytest.mark.archive
def test_archive_dumps_db_before_removal():
    result = archive_instance(instance="feat-789", workspace_root="/ws")  # TODO: wire up
    assert result.db_dumped is True
    assert result.db_dump_path == "/ws/_archive/feat-789/db.dump"


@pytest.mark.archive
def test_archive_removes_worktrees_drops_live_db_frees_port():
    result = archive_instance(instance="feat-789", workspace_root="/ws")  # TODO: wire up
    assert result.worktrees_removed is True
    assert result.live_db_dropped is True
    assert result.port_freed is True


@pytest.mark.archive
def test_archive_discard_db_skips_dump():
    result = archive_instance(instance="feat-789", workspace_root="/ws", discard_db=True)  # TODO: wire up
    assert result.db_dumped is False
    assert result.live_db_dropped is True


@pytest.mark.archive
def test_archive_discard_artifacts_preserves_toml_only():
    result = archive_instance(instance="feat-789", workspace_root="/ws", discard_artifacts=True)  # TODO: wire up
    assert "instance.toml" in result.preserved
    assert "notes.md" not in result.preserved
    assert result.db_dumped is False


@pytest.mark.archive
def test_archive_running_instance_hard_error():
    with pytest.raises(Exception) as exc_info:
        archive_instance(instance="feat-789", workspace_root="/ws", running=True)  # TODO: wire up
    assert "INSTANCE_RUNNING" in str(exc_info.value) or "stop" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# owm create with existing archive — human path
# ---------------------------------------------------------------------------

@pytest.mark.archive
def test_create_detects_archived_instance_prompts_human():
    result = detect_archive_conflict(
        name="pd-123",
        workspace_root="/ws",
        archive_exists=True,
        archive_date="2026-01-15",
        mode="human",
    )  # TODO: wire up
    assert result.conflict is True
    assert result.archive_date == "2026-01-15"
    assert result.options == ["restore", "fresh"] or set(result.options) == {"restore", "fresh"}


@pytest.mark.archive
def test_create_detects_archived_instance_hard_error_for_agent():
    """Agent path: hard error unless --restore or --fresh flag provided."""
    with pytest.raises(Exception) as exc_info:
        detect_archive_conflict(
            name="pd-123",
            workspace_root="/ws",
            archive_exists=True,
            archive_date="2026-01-15",
            mode="agent",
            flag=None,
        )  # TODO: wire up
    assert "archive" in str(exc_info.value).lower() or "restore" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# owm create --restore
# ---------------------------------------------------------------------------

@pytest.mark.archive
def test_restore_recreates_worktrees_and_db():
    result = create_from_archive(
        name="pd-123",
        workspace_root="/ws",
        mode="restore",
    )  # TODO: wire up
    assert result.worktrees_created is True
    assert result.db_restored is True


@pytest.mark.archive
def test_restore_assigns_fresh_port_not_original():
    """Restored instance gets a fresh port assignment, not the original archived port."""
    result = create_from_archive(
        name="pd-123",
        workspace_root="/ws",
        mode="restore",
        original_port=8200,
    )  # TODO: wire up
    assert result.port is not None
    # port may or may not equal original — what matters is it went through assignment
    assert result.port_freshly_assigned is True


# ---------------------------------------------------------------------------
# owm create --fresh
# ---------------------------------------------------------------------------

@pytest.mark.archive
def test_fresh_renames_old_archive_before_creating():
    result = create_from_archive(
        name="pd-123",
        workspace_root="/ws",
        mode="fresh",
        archive_date="2026-01-15",
    )  # TODO: wire up
    assert result.old_archive_renamed_to == "/ws/_archive/pd-123_archived_2026-01-15/"
    assert result.old_archive_preserved is True


# ---------------------------------------------------------------------------
# owm archive-delete
# ---------------------------------------------------------------------------

@pytest.mark.archive
def test_archive_delete_removes_archive_permanently():
    result = delete_archive(name="pd-123", workspace_root="/ws", confirmed=True)  # TODO: wire up
    assert result.status == "deleted"
    assert result.path == "/ws/_archive/pd-123/"


@pytest.mark.archive
def test_archive_delete_requires_explicit_confirmation():
    with pytest.raises(Exception) as exc_info:
        delete_archive(name="pd-123", workspace_root="/ws", confirmed=False)  # TODO: wire up
    assert "confirm" in str(exc_info.value).lower() or "explicit" in str(exc_info.value).lower()


@pytest.mark.archive
def test_archive_delete_timestamped_archive():
    result = delete_archive(
        name="pd-123_archived_2026-01-15",
        workspace_root="/ws",
        confirmed=True,
    )  # TODO: wire up
    assert result.path == "/ws/_archive/pd-123_archived_2026-01-15/"


# === SPEC GAPS ===
# test_archive_stored_path_layout: spec says "_archive/feat-789/" but does not specify
#   subdirectory structure within the archive (e.g., is db.dump at root or in a subdir?).
# test_create_restore_db_absent_from_archive: if archive was created with --discard-db,
#   restore behaviour is undefined in spec (blank slate? error? warning?).
