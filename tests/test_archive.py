"""
Tests for instance archival, restore, and archive-delete operations.
Covers: Archive section.

I/O helpers (_remove_worktrees, _pg_dump_archive, _dropdb_archive,
_remove_proxy_block, _capture_head_shas, _patch_archived_toml,
_strip_artifacts_from_dir) are patched in unit tests; smoke tests in
test_smoke_archive.py exercise the real filesystem path.
"""
import pytest
from unittest.mock import patch, MagicMock

from owm.archive import archive_instance, create_from_archive
from owm.archive import delete_archive, detect_archive_conflict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _infra_patches(*, discard_db=False, with_dump=True):
    """Return a list of (target, kwargs) for patching all I/O helpers."""
    patches = [
        patch("owm.archive._capture_head_shas", return_value={}),
        patch("owm.archive._remove_worktrees"),
        patch("owm.archive._dropdb_archive"),
        patch("owm.archive._remove_proxy_block", return_value=True),
        patch("owm.archive._strip_artifacts_from_dir"),
        patch("owm.archive._patch_archived_toml"),
        patch("owm.archive.shutil.move"),
        patch("owm.archive.os.makedirs"),
    ]
    if not discard_db:
        patches.append(patch("owm.archive._pg_dump_archive"))
    return patches


# ---------------------------------------------------------------------------
# owm archive — result shape
# ---------------------------------------------------------------------------

@pytest.mark.archive
def test_archive_default_preserves_toml_and_dump(standard_instance_toml, tmp_workspace):
    with patch("owm.archive._capture_head_shas", return_value={}), \
         patch("owm.archive._remove_worktrees"), \
         patch("owm.archive._pg_dump_archive"), \
         patch("owm.archive._dropdb_archive"), \
         patch("owm.archive._remove_proxy_block", return_value=True), \
         patch("owm.archive._strip_artifacts_from_dir"), \
         patch("owm.archive._patch_archived_toml"), \
         patch("owm.archive.shutil.move"), \
         patch("owm.archive.os.makedirs"):
        result = archive_instance(instance="feat-789", workspace_root=str(tmp_workspace))
    assert set(result.preserved) >= {"instance.toml", "db.dump"}
    assert result.archive_path == str(tmp_workspace / "_archive" / "feat-789") + "/"


@pytest.mark.archive
def test_archive_dumps_db_before_removal(standard_instance_toml, tmp_workspace):
    with patch("owm.archive._capture_head_shas", return_value={}), \
         patch("owm.archive._remove_worktrees"), \
         patch("owm.archive._pg_dump_archive"), \
         patch("owm.archive._dropdb_archive"), \
         patch("owm.archive._remove_proxy_block", return_value=True), \
         patch("owm.archive._strip_artifacts_from_dir"), \
         patch("owm.archive._patch_archived_toml"), \
         patch("owm.archive.shutil.move"), \
         patch("owm.archive.os.makedirs"):
        result = archive_instance(instance="feat-789", workspace_root=str(tmp_workspace))
    assert result.db_dumped is True
    assert result.db_dump_path is not None
    assert result.db_dump_path.endswith("db.dump")


@pytest.mark.archive
def test_archive_removes_worktrees_drops_db_frees_port(standard_instance_toml, tmp_workspace):
    with patch("owm.archive._capture_head_shas", return_value={}), \
         patch("owm.archive._remove_worktrees"), \
         patch("owm.archive._pg_dump_archive"), \
         patch("owm.archive._dropdb_archive"), \
         patch("owm.archive._remove_proxy_block", return_value=True), \
         patch("owm.archive._strip_artifacts_from_dir"), \
         patch("owm.archive._patch_archived_toml"), \
         patch("owm.archive.shutil.move"), \
         patch("owm.archive.os.makedirs"):
        result = archive_instance(instance="feat-789", workspace_root=str(tmp_workspace))
    assert result.worktrees_removed is True
    assert result.live_db_dropped is True
    assert result.port_freed is True


@pytest.mark.archive
def test_archive_discard_db_skips_dump(standard_instance_toml, tmp_workspace):
    with patch("owm.archive._capture_head_shas", return_value={}), \
         patch("owm.archive._remove_worktrees"), \
         patch("owm.archive._dropdb_archive"), \
         patch("owm.archive._remove_proxy_block", return_value=True), \
         patch("owm.archive._strip_artifacts_from_dir"), \
         patch("owm.archive._patch_archived_toml"), \
         patch("owm.archive.shutil.move"), \
         patch("owm.archive.os.makedirs"):
        result = archive_instance(
            instance="feat-789", workspace_root=str(tmp_workspace), discard_db=True
        )
    assert result.db_dumped is False
    assert result.live_db_dropped is True


@pytest.mark.archive
def test_archive_discard_artifacts_preserves_toml_only(standard_instance_toml, tmp_workspace):
    with patch("owm.archive._capture_head_shas", return_value={}), \
         patch("owm.archive._remove_worktrees"), \
         patch("owm.archive._dropdb_archive"), \
         patch("owm.archive._remove_proxy_block", return_value=True), \
         patch("owm.archive._patch_archived_toml"), \
         patch("owm.archive.shutil.move"), \
         patch("owm.archive.os.makedirs"):
        result = archive_instance(
            instance="feat-789", workspace_root=str(tmp_workspace), discard_artifacts=True
        )
    assert "instance.toml" in result.preserved
    assert "notes.md" not in result.preserved
    assert result.db_dumped is False


@pytest.mark.archive
def test_archive_running_instance_hard_error():
    with pytest.raises(Exception) as exc_info:
        archive_instance(instance="feat-789", workspace_root="/ws", running=True)
    assert "INSTANCE_RUNNING" in str(exc_info.value) or "stop" in str(exc_info.value).lower()


@pytest.mark.archive
def test_archive_already_archived_raises(tmp_workspace):
    (tmp_workspace / "_archive" / "feat-789").mkdir(parents=True)
    with pytest.raises(Exception) as exc_info:
        archive_instance(instance="feat-789", workspace_root=str(tmp_workspace))
    assert "ARCHIVE_CONFLICT" in str(exc_info.value)


# ---------------------------------------------------------------------------
# DB operations — xfail (need Postgres)
# ---------------------------------------------------------------------------

@pytest.mark.archive
def test_archive_db_dump_calls_pg_dump(standard_instance_toml, tmp_workspace):
    """pg_dump is called with correct db_name and pg_port from instance.toml."""
    with patch("owm.archive._capture_head_shas", return_value={}), \
         patch("owm.archive._remove_worktrees"), \
         patch("owm.archive._remove_proxy_block", return_value=True), \
         patch("owm.archive._strip_artifacts_from_dir"), \
         patch("owm.archive._patch_archived_toml"), \
         patch("owm.archive.shutil.move"), \
         patch("owm.archive.os.makedirs"), \
         patch("owm.archive.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        archive_instance(instance="feat-789", workspace_root=str(tmp_workspace))
    calls = [str(c) for c in mock_run.call_args_list]
    assert any("pg_dump" in c for c in calls)
    assert any("owm_test_feat789" in c for c in calls)


# ---------------------------------------------------------------------------
# owm create with existing archive
# ---------------------------------------------------------------------------

@pytest.mark.archive
def test_create_detects_archived_instance_prompts_human(tmp_path):
    (tmp_path / "_archive" / "pd-123").mkdir(parents=True)
    result = detect_archive_conflict(
        name="pd-123",
        workspace_root=str(tmp_path),
        archive_date="2026-01-15",
        mode="human",
    )
    assert result.conflict is True
    assert result.archive_date == "2026-01-15"
    assert set(result.options) == {"restore", "fresh"}


@pytest.mark.archive
def test_create_detects_archived_instance_hard_error_for_agent(tmp_path):
    (tmp_path / "_archive" / "pd-123").mkdir(parents=True)
    with pytest.raises(Exception) as exc_info:
        detect_archive_conflict(
            name="pd-123",
            workspace_root=str(tmp_path),
            archive_date="2026-01-15",
            mode="agent",
            flag=None,
        )
    assert "archive" in str(exc_info.value).lower() or "restore" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# owm create --restore / --fresh
# ---------------------------------------------------------------------------

@pytest.mark.archive
def test_restore_recreates_worktrees_and_db():
    result = create_from_archive(name="pd-123", workspace_root="/ws", mode="restore")
    assert result.worktrees_created is True
    assert result.db_restored is True


@pytest.mark.archive
def test_restore_assigns_fresh_port_not_original():
    result = create_from_archive(
        name="pd-123", workspace_root="/ws", mode="restore", original_port=8200,
    )
    assert result.port is not None
    assert result.port_freshly_assigned is True


@pytest.mark.archive
def test_fresh_renames_old_archive_before_creating():
    result = create_from_archive(
        name="pd-123", workspace_root="/ws", mode="fresh", archive_date="2026-01-15",
    )
    assert result.old_archive_renamed_to == "/ws/_archive/pd-123_archived_2026-01-15/"
    assert result.old_archive_preserved is True


# ---------------------------------------------------------------------------
# owm archive-delete
# ---------------------------------------------------------------------------

@pytest.mark.archive
def test_archive_delete_removes_archive_permanently(tmp_path):
    archive_dir = tmp_path / "_archive" / "pd-123"
    archive_dir.mkdir(parents=True)
    result = delete_archive(name="pd-123", workspace_root=str(tmp_path), confirmed=True)
    assert result.status == "deleted"
    assert not archive_dir.exists()


@pytest.mark.archive
def test_archive_delete_requires_explicit_confirmation():
    with pytest.raises(Exception) as exc_info:
        delete_archive(name="pd-123", workspace_root="/ws", confirmed=False)
    assert "confirm" in str(exc_info.value).lower() or "explicit" in str(exc_info.value).lower()


@pytest.mark.archive
def test_archive_delete_timestamped_archive(tmp_path):
    archive_dir = tmp_path / "_archive" / "pd-123_archived_2026-01-15"
    archive_dir.mkdir(parents=True)
    result = delete_archive(
        name="pd-123_archived_2026-01-15", workspace_root=str(tmp_path), confirmed=True,
    )
    assert result.path.endswith("pd-123_archived_2026-01-15/")
    assert not archive_dir.exists()


# === SPEC GAPS ===
# test_archive_stored_path_layout: spec says "_archive/feat-789/" but does not specify
#   subdirectory structure within the archive (e.g., is db.dump at root or in a subdir?).
# test_create_restore_db_absent_from_archive: if archive was created with --discard-db,
#   restore behaviour is undefined in spec (blank slate? error? warning?).
