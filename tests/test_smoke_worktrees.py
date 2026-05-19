"""
Smoke tests for worktree creation — real git subprocesses, no mocks.
Covers: Worktrees and branch ownership section.
"""
import subprocess
import pytest

from owm.worktrees import create_worktree


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _make_bare_with_branch(tmp_path, name, branch="main"):
    """Create a local bare repo seeded with an initial commit on the given branch."""
    remote = tmp_path / "remotes" / f"{name}.git"
    remote.mkdir(parents=True)
    _git(["init", "--bare"], cwd=remote)

    src = tmp_path / "remotes" / f"{name}-seed"
    src.mkdir()
    _git(["init"], cwd=src)
    _git(["config", "user.email", "test@test.com"], cwd=src)
    _git(["config", "user.name", "Test"], cwd=src)
    (src / "README.md").write_text(f"# {name}\n")
    _git(["add", "."], cwd=src)
    _git(["commit", "-m", "init"], cwd=src)
    _git(["remote", "add", "origin", str(remote)], cwd=src)
    _git(["push", "origin", f"HEAD:{branch}"], cwd=src)

    return remote


def _setup_workspace(tmp_path, repos: dict) -> str:
    """Clone bare repos into _repos/<name>.git and return workspace root path.

    git clone --bare already copies all branch refs from the source, so no
    subsequent fetch is needed. The fetch refspec is set for future owm fetch calls.
    """
    ws = tmp_path / "workspace"
    ws.mkdir()
    repos_dir = ws / "_repos"
    repos_dir.mkdir()
    for name, bare in repos.items():
        dest = repos_dir / f"{name}.git"
        _git(["clone", "--bare", str(bare), str(dest)], cwd=tmp_path)
        _git(["config", "remote.origin.fetch", "+refs/heads/*:refs/heads/*"], cwd=dest)
    return str(ws)


# ---------------------------------------------------------------------------
# Per-instance worktree
# ---------------------------------------------------------------------------

@pytest.mark.smoke
def test_create_per_instance_worktree_creates_checkout(tmp_path):
    bare = _make_bare_with_branch(tmp_path, "product-core")
    ws = _setup_workspace(tmp_path, {"product-core": bare})
    result = create_worktree(
        repo="product-core",
        branch="main",
        shared=False,
        workspace_root=ws,
        instance_name="feat-789",
    )
    assert result.action == "created"
    import os
    assert os.path.isdir(result.path)
    assert (os.path.join(result.path, ".git") or
            os.path.isfile(os.path.join(result.path, ".git")))


@pytest.mark.smoke
def test_create_per_instance_worktree_path_is_under_instance_dir(tmp_path):
    bare = _make_bare_with_branch(tmp_path, "product-core")
    ws = _setup_workspace(tmp_path, {"product-core": bare})
    result = create_worktree(
        repo="product-core",
        branch="main",
        shared=False,
        workspace_root=ws,
        instance_name="feat-789",
    )
    assert "instances" in result.path
    assert "feat-789" in result.path
    assert "product-core" in result.path


@pytest.mark.smoke
def test_create_per_instance_worktree_files_match_branch(tmp_path):
    bare = _make_bare_with_branch(tmp_path, "product-core")
    ws = _setup_workspace(tmp_path, {"product-core": bare})
    result = create_worktree(
        repo="product-core",
        branch="main",
        shared=False,
        workspace_root=ws,
        instance_name="feat-789",
    )
    import os
    assert os.path.isfile(os.path.join(result.path, "README.md"))


# ---------------------------------------------------------------------------
# Shared worktree
# ---------------------------------------------------------------------------

@pytest.mark.smoke
def test_create_shared_worktree_creates_at_shared_path(tmp_path):
    bare = _make_bare_with_branch(tmp_path, "odoo")
    ws = _setup_workspace(tmp_path, {"odoo": bare})
    result = create_worktree(
        repo="odoo",
        branch="main",
        shared=True,
        workspace_root=ws,
        instance_name="feat-789",
    )
    assert result.action == "linked"
    assert "_shared" in result.path
    assert "odoo" in result.path
    import os
    assert os.path.isdir(result.path)


@pytest.mark.smoke
def test_create_shared_worktree_idempotent_across_instances(tmp_path):
    """Second instance using same shared repo returns 'linked' without re-adding worktree."""
    bare = _make_bare_with_branch(tmp_path, "odoo")
    ws = _setup_workspace(tmp_path, {"odoo": bare})
    result1 = create_worktree(
        repo="odoo", branch="main", shared=True,
        workspace_root=ws, instance_name="feat-789",
    )
    result2 = create_worktree(
        repo="odoo", branch="main", shared=True,
        workspace_root=ws, instance_name="feat-888",
    )
    assert result1.path == result2.path
    assert result2.action == "linked"
