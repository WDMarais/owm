"""
Tests for per-instance session context files (setup.md, notes.md, review/).
Covers: Session context files section.
"""
import pytest

from owm.session_context import get_context_files, write_review_snapshot
from owm.session_context import build_agent_context, status_has_setup_md


# ---------------------------------------------------------------------------
# File structure and presence
# ---------------------------------------------------------------------------

@pytest.mark.session_context
def test_absent_setup_md_is_happy_path(tmp_path):
    instance_dir = tmp_path / "feat-789"
    instance_dir.mkdir()
    files = get_context_files(str(instance_dir))
    assert files.setup_md is None
    assert files.happy_path is True


@pytest.mark.session_context
def test_present_setup_md_surfaced_in_status(tmp_path):
    instance_dir = tmp_path / "feat-789"
    instance_dir.mkdir()
    (instance_dir / "setup.md").write_text("# Setup")
    result = status_has_setup_md(instance="feat-789", instance_dir=str(instance_dir))
    assert result.setup_md_present is True
    assert result.surfaced_in_status is True


@pytest.mark.session_context
def test_notes_md_present(tmp_path):
    instance_dir = tmp_path / "feat-789"
    instance_dir.mkdir()
    (instance_dir / "notes.md").write_text("# Notes")
    files = get_context_files(str(instance_dir))
    assert files.notes_md is not None


@pytest.mark.session_context
def test_review_dir_contains_dated_snapshots(tmp_path):
    instance_dir = tmp_path / "feat-789"
    review_dir = instance_dir / "review"
    review_dir.mkdir(parents=True)
    (review_dir / "2026-05-16-initial.md").write_text("# Review 1")
    (review_dir / "2026-05-17-post-rebase.md").write_text("# Review 2")
    files = get_context_files(str(instance_dir))
    assert len(files.review_snapshots) == 2


# ---------------------------------------------------------------------------
# Review file naming
# ---------------------------------------------------------------------------

@pytest.mark.session_context
def test_review_file_naming_initial(tmp_path):
    instance_dir = tmp_path / "feat-789"
    instance_dir.mkdir()
    result = write_review_snapshot(
        instance="feat-789",
        instance_dir=str(instance_dir),
        trigger="initial",
        date="2026-05-16",
        content="# Review\nLGTM",
    )
    assert result.path == str(instance_dir / "review" / "2026-05-16-initial.md")


@pytest.mark.session_context
def test_review_file_naming_post_rebase(tmp_path):
    instance_dir = tmp_path / "feat-789"
    instance_dir.mkdir()
    result = write_review_snapshot(
        instance="feat-789",
        instance_dir=str(instance_dir),
        trigger="post-rebase",
        date="2026-05-17",
        content="# Post-rebase review",
    )
    assert result.path.endswith("2026-05-17-post-rebase.md")


@pytest.mark.session_context
def test_review_write_never_overwrites_existing(tmp_path):
    """Agent writes blind review → always appends new dated file, never overwrites."""
    instance_dir = tmp_path / "feat-789"
    review_dir = instance_dir / "review"
    review_dir.mkdir(parents=True)
    (review_dir / "2026-05-16-initial.md").write_text("# Existing review")

    result = write_review_snapshot(
        instance="feat-789",
        instance_dir=str(instance_dir),
        trigger="initial",
        date="2026-05-16",
        content="# New review",
    )
    assert result.path != str(review_dir / "2026-05-16-initial.md")
    assert (instance_dir / "review" / "2026-05-16-initial.md").read_text() == "# Existing review"


@pytest.mark.session_context
def test_review_latest_file_is_canonical(tmp_path):
    instance_dir = tmp_path / "feat-789"
    review_dir = instance_dir / "review"
    review_dir.mkdir(parents=True)
    (review_dir / "2026-05-16-initial.md").write_text("# Review 1")
    (review_dir / "2026-05-17-post-rebase.md").write_text("# Review 2")
    files = get_context_files(str(instance_dir))
    assert "post-rebase" in files.latest_review or files.latest_review.endswith("post-rebase.md")


# ---------------------------------------------------------------------------
# owm_agent_context consumption
# ---------------------------------------------------------------------------

@pytest.mark.session_context
def test_agent_context_reads_notes_and_latest_review():
    result = build_agent_context(
        instance="feat-789",
        role=None,
        workspace_boilerplate="## Workspace context",
        instance_notes="## Instance notes",
        review_files=["review/2026-05-16-initial.md", "review/2026-05-17-post-rebase.md"],
        setup_md=None,
    )
    assert "## Instance notes" in result.context
    assert "post-rebase" in result.context or "2026-05-17" in result.context


@pytest.mark.session_context
def test_agent_context_excludes_review_history():
    """Only latest review file included; full history excluded (noise)."""
    result = build_agent_context(
        instance="feat-789",
        role=None,
        workspace_boilerplate="## Workspace",
        instance_notes="## Notes",
        review_files=["review/2026-05-16-initial.md", "review/2026-05-17-post-rebase.md"],
        setup_md=None,
    )
    assert "2026-05-16-initial" not in result.context


@pytest.mark.session_context
def test_agent_context_missing_notes_not_an_error():
    result = build_agent_context(
        instance="feat-789",
        role=None,
        workspace_boilerplate="## Workspace",
        instance_notes=None,
        review_files=[],
        setup_md=None,
    )
    assert result.sources["instance"] is None
    assert result.context is not None


# === SPEC GAPS ===
# test_review_file_collision_when_same_trigger_same_date: spec says "never overwrites"
#   but does not specify the naming disambiguation strategy (suffix counter? timestamp?).
# test_setup_md_included_in_agent_context: spec says "setup.md included if present"
#   in owm_agent_context; the exact include behaviour (concatenated? referenced?) not shown.
