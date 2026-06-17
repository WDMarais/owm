"""
Tests for worktree creation and branch ownership rules.
Covers: Worktrees and branch ownership section.
"""
import pytest
from unittest.mock import patch

from owm.worktrees import (
    resolve_worktree_path,
    push_branch,
    check_shared_commit_warning,
)
from owm.worktrees import create_worktree, check_edit_allowed


# ---------------------------------------------------------------------------
# Worktree path resolution
# ---------------------------------------------------------------------------

@pytest.mark.worktrees
def test_shared_repo_resolves_to_shared_worktree_path():
    """odoo = "19.0:shared" → path is _shared/odoo/19.0, no per-instance checkout."""
    result = resolve_worktree_path(
        repo="odoo",
        branch="19.0",
        shared=True,
        workspace_root="/ws",
        instance_name="feat-789",
    )
    assert result.path == "/ws/_shared/odoo/19.0"
    assert result.per_instance is False


@pytest.mark.worktrees
def test_per_instance_repo_resolves_to_instance_directory():
    """product-core = "feat-789-dev:dev" → path is instances/feat-789/product-core."""
    result = resolve_worktree_path(
        repo="product-core",
        branch="feat-789-dev",
        shared=False,
        workspace_root="/ws",
        instance_name="feat-789",
    )
    assert result.path == "/ws/instances/feat-789/product-core"
    assert result.per_instance is True


@pytest.mark.worktrees
def test_create_instance_links_shared_worktree(tmp_path):
    """Creating an instance with a shared repo uses the existing shared worktree."""
    with patch("owm.worktrees._git_worktree_add"):
        result = create_worktree(
            repo="odoo",
            branch="19.0",
            shared=True,
            workspace_root=str(tmp_path),
            instance_name="feat-789",
        )
    assert result.action == "linked"
    assert result.path == str(tmp_path / "_shared" / "odoo" / "19.0")


@pytest.mark.worktrees
def test_create_instance_creates_per_instance_worktree(tmp_path):
    with patch("owm.worktrees._git_worktree_add"), \
         patch("owm.worktrees._branch_exists", return_value=True):
        result = create_worktree(
            repo="product-core",
            branch="feat-789-dev",
            shared=False,
            workspace_root=str(tmp_path),
            instance_name="feat-789",
        )
    assert result.action == "created"
    assert "feat-789" in result.path


# ---------------------------------------------------------------------------
# Branch intent: +exists / +create
# ---------------------------------------------------------------------------

@pytest.mark.worktrees
def test_no_flag_branch_present_checks_out(tmp_path):
    with patch("owm.worktrees._branch_exists", return_value=True), \
         patch("owm.worktrees._git_worktree_add") as mock_add:
        result = create_worktree(
            repo="product-core", branch="feat-789", shared=False,
            workspace_root=str(tmp_path), instance_name="feat-789",
        )
    mock_add.assert_called_once()
    assert result.action == "created"


@pytest.mark.worktrees
def test_exists_flag_branch_present_checks_out(tmp_path):
    with patch("owm.worktrees._branch_exists", return_value=True), \
         patch("owm.worktrees._git_worktree_add") as mock_add:
        result = create_worktree(
            repo="product-core", branch="feat-789", shared=False,
            workspace_root=str(tmp_path), instance_name="feat-789",
            assert_exists=True,
        )
    mock_add.assert_called_once()
    assert result.action == "created"


@pytest.mark.worktrees
def test_create_flag_branch_present_checks_out_existing(tmp_path):
    with patch("owm.worktrees._branch_exists", return_value=True), \
         patch("owm.worktrees._git_worktree_add") as mock_add:
        create_worktree(
            repo="product-core", branch="feat-789", shared=False,
            workspace_root=str(tmp_path), instance_name="feat-789",
            base="main", create=True,
        )
    mock_add.assert_called_once()


@pytest.mark.worktrees
def test_exists_and_create_together_raises_config_error(tmp_path):
    with pytest.raises(Exception) as exc_info:
        create_worktree(
            repo="product-core", branch="feat-789", shared=False,
            workspace_root=str(tmp_path), instance_name="feat-789",
            assert_exists=True, create=True,
        )
    assert "mutually exclusive" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# Push permission enforcement
# ---------------------------------------------------------------------------

@pytest.mark.worktrees
def test_push_owned_branch_succeeds():
    result = push_branch(
        instance="feat-789",
        repo="product-core",
        branch="feat-789-dev",
        readonly=False,
        shared=False,
        override=False,
    )
    assert result.status == "pushed"


@pytest.mark.worktrees
def test_push_readonly_branch_refused():
    """review-101: product-core is readonly → push refused, no override flag."""
    with pytest.raises(Exception) as exc_info:
        push_branch(
            instance="review-101",
            repo="product-core",
            branch="feat-789-dev",
            readonly=True,
            shared=False,
            override=False,
        )
    assert "NOT_OWNED" in str(exc_info.value) or "not configured as owned" in str(exc_info.value).lower()


@pytest.mark.worktrees
def test_push_readonly_branch_with_override_flag_allowed():
    """--override allows push on readonly branch when explicitly set in instance config."""
    result = push_branch(
        instance="review-101",
        repo="product-core",
        branch="feat-789-dev",
        readonly=True,
        shared=False,
        override=True,
    )
    assert result.status == "pushed"


@pytest.mark.worktrees
def test_push_readonly_branch_override_flag_not_in_config_still_refused():
    """override=True at CLI but override not declared in instance config → refused."""
    with pytest.raises(Exception) as exc_info:
        push_branch(
            instance="review-101",
            repo="product-core",
            branch="feat-789-dev",
            readonly=True,
            shared=False,
            override=True,
            override_allowed_in_config=False,  # instance.toml does not permit override
        )
    assert "NOT_OWNED" in str(exc_info.value) or "not" in str(exc_info.value).lower()


@pytest.mark.worktrees
def test_push_shared_branch_refused():
    """owm push on a shared worktree is always refused."""
    with pytest.raises(Exception) as exc_info:
        push_branch(
            instance="feat-789",
            repo="odoo",
            branch="19.0",
            readonly=False,
            shared=True,
            override=False,
        )
    assert "SHARED_REPO" in str(exc_info.value) or "shared" in str(exc_info.value).lower()


@pytest.mark.worktrees
def test_push_shared_branch_error_includes_raw_git_command():
    """Error message for shared push includes the direct git command."""
    try:
        push_branch(
            instance="feat-789",
            repo="odoo",
            branch="19.0",
            readonly=False,
            shared=True,
            override=False,
        )
    except Exception as exc:
        msg = str(exc)
        assert "git" in msg and "push" in msg
        assert "_shared/odoo/19.0" in msg or "shared" in msg


# ---------------------------------------------------------------------------
# Shared worktree commit warning
# ---------------------------------------------------------------------------

@pytest.mark.worktrees
def test_shared_worktree_commit_emits_warning():
    """Commit in a shared worktree → warning that it is visible to all instances."""
    result = check_shared_commit_warning(
        repo="odoo",
        branch="19.0",
        shared=True,
        has_new_commit=True,
    )
    assert result.warning is True
    assert "shared" in result.message.lower() or "visible" in result.message.lower()


@pytest.mark.worktrees
def test_per_instance_worktree_commit_no_warning():
    result = check_shared_commit_warning(
        repo="product-core",
        branch="feat-789-dev",
        shared=False,
        has_new_commit=True,
    )
    assert result.warning is False


# ---------------------------------------------------------------------------
# Local edits in readonly worktree
# ---------------------------------------------------------------------------


@pytest.mark.worktrees
def test_edit_in_readonly_worktree_is_allowed():
    """readonly flag blocks push, not local edits or commits."""
    result = check_edit_allowed(readonly=True)
    assert result.allowed is True


# ---------------------------------------------------------------------------
# Worktree existence — .git file required
# ---------------------------------------------------------------------------

@pytest.mark.worktrees
def test_plain_dir_at_worktree_path_is_not_treated_as_existing(tmp_path):
    """A directory without a .git file is not a worktree — creation proceeds."""
    stray = tmp_path / "_shared" / "odoo" / "19.0"
    stray.mkdir(parents=True)

    with patch("owm.worktrees._git_worktree_add") as mock_add:
        result = create_worktree(
            repo="odoo",
            branch="19.0",
            shared=True,
            workspace_root=str(tmp_path),
            instance_name="feat-789",
        )
    mock_add.assert_called_once()
    assert result.action == "linked"


@pytest.mark.worktrees
def test_dir_with_git_file_is_treated_as_existing_worktree(tmp_path):
    """A directory with a .git file is a valid worktree — creation is skipped."""
    wt = tmp_path / "_shared" / "odoo" / "19.0"
    wt.mkdir(parents=True)
    (wt / ".git").write_text("gitdir: ../../../_repos/odoo.git/worktrees/19.0\n")

    with patch("owm.worktrees._git_worktree_add") as mock_add:
        result = create_worktree(
            repo="odoo",
            branch="19.0",
            shared=True,
            workspace_root=str(tmp_path),
            instance_name="feat-789",
        )
    mock_add.assert_not_called()
    assert result.action == "linked"


# === SPEC GAPS ===
# test_push_override_flag_location: spec says "override flag explicitly set in instance config"
#   but does not specify the exact config key name or section in instance.toml.
# test_shared_worktree_creation_when_not_yet_cloned: spec says shared worktrees are created
#   during owm init, not owm create — the handoff between init and create worktree resolution
#   is not explicitly specced.
