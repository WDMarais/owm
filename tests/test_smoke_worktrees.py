"""
Smoke tests for worktree creation — real git subprocesses, no mocks.
Covers: Worktrees and branch ownership section.
"""
import os
import subprocess
import pytest

from owm.errors import OwmError, BRANCH_NOT_FOUND, BRANCH_ALREADY_EXISTS, WORKTREE_ADD_FAILED
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


# ---------------------------------------------------------------------------
# Seeding a per-instance worktree from origin (branch on origin, not yet local)
# ---------------------------------------------------------------------------

def _make_remote_with_branches(tmp_path, name, branches):
    """A bare 'remote' repo with one commit pushed to each named branch."""
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
    for b in branches:
        _git(["push", "origin", f"HEAD:{b}"], cwd=src)
    return remote


def _setup_workspace_origin_tracking(tmp_path, repos):
    """Set up _repos/<name>.git the way owm does in production: bare init +
    origin remote + fetch, so branches land in refs/remotes/origin/* and the
    bare repo has no refs/heads/* until a worktree is created. (The other
    fixture's `clone --bare` puts everything in refs/heads, which doesn't
    exercise the origin-seed path.)"""
    ws = tmp_path / "workspace"
    ws.mkdir()
    repos_dir = ws / "_repos"
    repos_dir.mkdir()
    for name, remote in repos.items():
        dest = repos_dir / f"{name}.git"
        dest.mkdir()
        _git(["init", "--bare"], cwd=dest)
        _git(["remote", "add", "origin", str(remote)], cwd=dest)
        _git(["fetch", "origin"], cwd=dest)
    return str(ws)


@pytest.mark.smoke
def test_create_per_instance_worktree_seeds_from_origin_when_not_local(tmp_path):
    """Branch exists on origin but was never checked out locally, and no base is
    given — create_worktree seeds a local branch from origin/<branch> anyway."""
    remote = _make_remote_with_branches(tmp_path, "product-core", ["main", "colleague-pr"])
    ws = _setup_workspace_origin_tracking(tmp_path, {"product-core": remote})
    bare = os.path.join(ws, "_repos", "product-core.git")

    # Precondition: the branch is origin-only in the bare repo.
    assert subprocess.run(["git", "rev-parse", "--verify", "refs/heads/colleague-pr"],
                          cwd=bare, capture_output=True).returncode != 0
    assert subprocess.run(["git", "rev-parse", "--verify", "refs/remotes/origin/colleague-pr"],
                          cwd=bare, capture_output=True).returncode == 0

    result = create_worktree(
        repo="product-core", branch="colleague-pr", shared=False,
        workspace_root=ws, instance_name="review-1",
    )
    assert result.action == "created"
    assert os.path.isfile(os.path.join(result.path, "README.md"))
    # A local branch now exists (seeded from origin).
    assert subprocess.run(["git", "rev-parse", "--verify", "refs/heads/colleague-pr"],
                          cwd=bare, capture_output=True).returncode == 0


@pytest.mark.smoke
def test_create_per_instance_worktree_raises_when_branch_absent_everywhere(tmp_path):
    """No local branch, no origin branch, no base — clear BRANCH_NOT_FOUND that
    names the branch and hints at +create."""
    remote = _make_remote_with_branches(tmp_path, "product-core", ["main"])
    ws = _setup_workspace_origin_tracking(tmp_path, {"product-core": remote})
    with pytest.raises(OwmError) as exc:
        create_worktree(
            repo="product-core", branch="ghost-branch", shared=False,
            workspace_root=ws, instance_name="review-1",
        )
    assert exc.value.code == BRANCH_NOT_FOUND
    assert "ghost-branch" in str(exc.value)
    assert "+create" in str(exc.value)


@pytest.mark.smoke
def test_create_per_instance_worktree_exists_flag_missing_raises(tmp_path):
    """+exists on a branch absent both locally and on origin raises BRANCH_NOT_FOUND."""
    remote = _make_remote_with_branches(tmp_path, "product-core", ["main"])
    ws = _setup_workspace_origin_tracking(tmp_path, {"product-core": remote})
    with pytest.raises(OwmError) as exc:
        create_worktree(
            repo="product-core", branch="ghost-branch", shared=False,
            workspace_root=ws, instance_name="review-1",
            assert_exists=True,
        )
    assert exc.value.code == BRANCH_NOT_FOUND


@pytest.mark.smoke
def test_create_per_instance_worktree_create_flag_seeds_from_base(tmp_path):
    """+create with a base, branch absent locally and on origin — a new branch is
    created from the base and checked out."""
    remote = _make_remote_with_branches(tmp_path, "product-core", ["main"])
    ws = _setup_workspace_origin_tracking(tmp_path, {"product-core": remote})
    bare = os.path.join(ws, "_repos", "product-core.git")

    result = create_worktree(
        repo="product-core", branch="brand-new", shared=False,
        workspace_root=ws, instance_name="review-1",
        base="origin/main", create=True,
    )
    assert result.action == "created"
    assert os.path.isfile(os.path.join(result.path, "README.md"))
    assert subprocess.run(["git", "rev-parse", "--verify", "refs/heads/brand-new"],
                          cwd=bare, capture_output=True).returncode == 0


@pytest.mark.smoke
def test_create_per_instance_worktree_create_flag_refuses_existing_origin_branch(tmp_path):
    """create asserts the branch is new — when it already exists on origin, refuse
    with BRANCH_ALREADY_EXISTS rather than silently checking out the upstream branch."""
    remote = _make_remote_with_branches(tmp_path, "product-core", ["main", "colleague-pr"])
    ws = _setup_workspace_origin_tracking(tmp_path, {"product-core": remote})

    with pytest.raises(OwmError) as exc:
        create_worktree(
            repo="product-core", branch="colleague-pr", shared=False,
            workspace_root=ws, instance_name="review-1",
            base="origin/main", create=True,
        )
    assert exc.value.code == BRANCH_ALREADY_EXISTS
    assert "colleague-pr" in str(exc.value)


@pytest.mark.smoke
def test_create_per_instance_worktree_bad_base_surfaces_git_error(tmp_path):
    """create from a base that does not exist — git's own message (invalid reference)
    is surfaced as a clean OwmError instead of a bare CalledProcessError traceback."""
    remote = _make_remote_with_branches(tmp_path, "product-core", ["main"])
    ws = _setup_workspace_origin_tracking(tmp_path, {"product-core": remote})

    with pytest.raises(OwmError) as exc:
        create_worktree(
            repo="product-core", branch="brand-new", shared=False,
            workspace_root=ws, instance_name="review-1",
            base="no-such-base", create=True,
        )
    assert exc.value.code == WORKTREE_ADD_FAILED
    assert "no-such-base" in str(exc.value)
    assert "invalid reference" in str(exc.value)
