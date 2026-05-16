"""
Tests for per-instance session context files (setup.md, notes.md, review/).
Covers: Session context files section.
"""
import pytest

# TODO: from owm.session_context import get_context_files, write_review_snapshot
# TODO: from owm.session_context import build_agent_context, status_has_setup_md

def get_context_files(*args, **kwargs):
    raise NotImplementedError

def write_review_snapshot(*args, **kwargs):
    raise NotImplementedError

def build_agent_context(*args, **kwargs):
    raise NotImplementedError

def status_has_setup_md(*args, **kwargs):
    raise NotImplementedError


# ---------------------------------------------------------------------------
# File structure and presence
# ---------------------------------------------------------------------------

@pytest.mark.session_context
def test_absent_setup_md_is_happy_path():
    files = get_context_files(instance_dir="/ws/instances/feat-789", files_present=[])  # TODO: wire up
    assert files.setup_md is None
    assert files.happy_path is True


@pytest.mark.session_context
def test_present_setup_md_surfaced_in_status():
    result = status_has_setup_md(
        instance="feat-789",
        instance_dir="/ws/instances/feat-789",
        setup_md_present=True,
    )  # TODO: wire up
    assert result.setup_md_present is True
    assert result.surfaced_in_status is True


@pytest.mark.session_context
def test_notes_md_present():
    files = get_context_files(
        instance_dir="/ws/instances/feat-789",
        files_present=["notes.md"],
    )  # TODO: wire up
    assert files.notes_md is not None


@pytest.mark.session_context
def test_review_dir_contains_dated_snapshots():
    files = get_context_files(
        instance_dir="/ws/instances/feat-789",
        files_present=["review/2026-05-16-initial.md", "review/2026-05-17-post-rebase.md"],
    )  # TODO: wire up
    assert len(files.review_snapshots) == 2


# ---------------------------------------------------------------------------
# Review file naming
# ---------------------------------------------------------------------------

@pytest.mark.session_context
def test_review_file_naming_initial():
    result = write_review_snapshot(
        instance="feat-789",
        instance_dir="/ws/instances/feat-789",
        trigger="initial",
        date="2026-05-16",
        content="# Review\nLGTM",
    )  # TODO: wire up
    assert result.path == "/ws/instances/feat-789/review/2026-05-16-initial.md"


@pytest.mark.session_context
def test_review_file_naming_post_rebase():
    result = write_review_snapshot(
        instance="feat-789",
        instance_dir="/ws/instances/feat-789",
        trigger="post-rebase",
        date="2026-05-17",
        content="# Post-rebase review",
    )  # TODO: wire up
    assert result.path.endswith("2026-05-17-post-rebase.md")


@pytest.mark.session_context
def test_review_write_never_overwrites_existing():
    """Agent writes blind review → always appends new dated file, never overwrites."""
    existing = ["review/2026-05-16-initial.md"]
    result = write_review_snapshot(
        instance="feat-789",
        instance_dir="/ws/instances/feat-789",
        trigger="initial",
        date="2026-05-16",
        content="# New review",
        existing_files=existing,
    )  # TODO: wire up
    assert result.path not in existing
    assert "2026-05-16-initial" not in result.path or result.path != "/ws/instances/feat-789/review/2026-05-16-initial.md"


@pytest.mark.session_context
def test_review_latest_file_is_canonical():
    files = get_context_files(
        instance_dir="/ws/instances/feat-789",
        files_present=[
            "review/2026-05-16-initial.md",
            "review/2026-05-17-post-rebase.md",
        ],
    )  # TODO: wire up
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
    )  # TODO: wire up
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
    )  # TODO: wire up
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
    )  # TODO: wire up
    assert result.sources["instance"] is None
    assert result.context is not None


# === SPEC GAPS ===
# test_review_file_collision_when_same_trigger_same_date: spec says "never overwrites"
#   but does not specify the naming disambiguation strategy (suffix counter? timestamp?).
# test_setup_md_included_in_agent_context: spec says "setup.md included if present"
#   in owm_agent_context; the exact include behaviour (concatenated? referenced?) not shown.
