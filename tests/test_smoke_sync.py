"""
Smoke tests for sync.py git I/O helpers.
No mocks — every test runs real git subprocesses against temp repos.

All helpers are tested via simple clones (not bare+worktree) so that the
upstream tracking branch (@{u}) is configured automatically by git clone.
git_fetch_bare is tested separately with a bare clone since it only needs
fetch, not tracking.
"""
import subprocess
from pathlib import Path

import pytest

from owm.sync import (
    read_repo_state,
    has_local_commits,
    git_run,
    git_fetch_bare,
    git_fast_forward,
    git_rebase,
    git_push,
    git_reset_hard,
)
from owm.errors import OwmError, GIT_COMMAND_FAILED


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------

def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _git_config(path):
    _git("config", "user.email", "test@owm.test", cwd=path)
    _git("config", "user.name", "owm-test", cwd=path)


def _upstream(tmp_path: Path, name: str = "repo") -> Path:
    """Init a non-bare upstream with one initial commit."""
    up = tmp_path / "upstream" / name
    up.mkdir(parents=True)
    _git("init", "-b", "main", cwd=up)
    _git_config(up)
    (up / "README.md").write_text(f"# {name}\n")
    _git("add", ".", cwd=up)
    _git("commit", "-m", "initial", cwd=up)
    return up


def _bare_upstream(tmp_path: Path, name: str = "repo") -> Path:
    """Init a bare upstream (accepts pushes; used for git_push smoke tests)."""
    stage = tmp_path / "stage" / name
    stage.mkdir(parents=True)
    _git("init", "-b", "main", cwd=stage)
    _git_config(stage)
    (stage / "README.md").write_text(f"# {name}\n")
    _git("add", ".", cwd=stage)
    _git("commit", "-m", "initial", cwd=stage)
    bare = tmp_path / "bare_upstream" / f"{name}.git"
    bare.parent.mkdir(parents=True)
    subprocess.run(["git", "clone", "--bare", str(stage), str(bare)],
                   check=True, capture_output=True)
    return bare


def _clone(upstream: Path, dest: Path) -> Path:
    """Normal (non-bare) clone; sets up origin tracking automatically."""
    subprocess.run(["git", "clone", str(upstream), str(dest)], check=True, capture_output=True)
    _git_config(dest)
    return dest


def _commit(repo: Path, filename: str, content: str, message: str = "test commit"):
    (repo / filename).write_text(content)
    _git("add", ".", cwd=repo)
    _git("commit", "-m", message, cwd=repo)


def _current_head(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True, check=True
    ).stdout.strip()


# ---------------------------------------------------------------------------
# read_repo_state
# ---------------------------------------------------------------------------

@pytest.mark.smoke
def test_read_repo_state_clean(tmp_path):
    up = _upstream(tmp_path)
    clone = _clone(up, tmp_path / "clone")
    assert read_repo_state(str(clone))["status"] == "clean"


@pytest.mark.smoke
def test_read_repo_state_dirty_staged(tmp_path):
    up = _upstream(tmp_path)
    clone = _clone(up, tmp_path / "clone")
    (clone / "README.md").write_text("modified content")
    _git("add", ".", cwd=clone)
    assert read_repo_state(str(clone))["status"] == "dirty"


@pytest.mark.smoke
def test_read_repo_state_dirty_untracked(tmp_path):
    """Untracked files show up in --porcelain output → treated as dirty."""
    up = _upstream(tmp_path)
    clone = _clone(up, tmp_path / "clone")
    (clone / "new_file.txt").write_text("untracked")
    assert read_repo_state(str(clone))["status"] == "dirty"


@pytest.mark.smoke
def test_read_repo_state_behind(tmp_path):
    up = _upstream(tmp_path)
    clone = _clone(up, tmp_path / "clone")
    _commit(up, "v2.txt", "v2", "upstream v2")
    _git("fetch", "origin", cwd=clone)
    state = read_repo_state(str(clone))
    assert state["status"] == "behind"
    assert state["behind_by"] == 1


@pytest.mark.smoke
def test_read_repo_state_ahead(tmp_path):
    up = _upstream(tmp_path)
    clone = _clone(up, tmp_path / "clone")
    _commit(clone, "local.txt", "local", "local commit")
    state = read_repo_state(str(clone))
    assert state["status"] == "ahead"
    assert state["ahead_by"] == 1


@pytest.mark.smoke
def test_read_repo_state_diverged(tmp_path):
    up = _upstream(tmp_path)
    clone = _clone(up, tmp_path / "clone")
    _commit(up, "upstream.txt", "up", "upstream commit")
    _git("fetch", "origin", cwd=clone)
    _commit(clone, "local.txt", "local", "local commit")
    state = read_repo_state(str(clone))
    assert state["status"] == "diverged"
    assert state["ahead_by"] == 1
    assert state["behind_by"] == 1


@pytest.mark.smoke
def test_read_repo_state_no_upstream_returns_clean(tmp_path):
    """Repo with no upstream tracking branch → @{u} fails → safe 'clean' default."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-b", "main", cwd=repo)
    _git_config(repo)
    (repo / "README.md").write_text("hi")
    _git("add", ".", cwd=repo)
    _git("commit", "-m", "init", cwd=repo)
    assert read_repo_state(str(repo))["status"] == "clean"


# ---------------------------------------------------------------------------
# has_local_commits
# ---------------------------------------------------------------------------

@pytest.mark.smoke
def test_has_local_commits_false_when_synced(tmp_path):
    up = _upstream(tmp_path)
    clone = _clone(up, tmp_path / "clone")
    assert has_local_commits(str(clone)) is False


@pytest.mark.smoke
def test_has_local_commits_true_when_ahead(tmp_path):
    up = _upstream(tmp_path)
    clone = _clone(up, tmp_path / "clone")
    _commit(clone, "local.txt", "local", "local commit")
    assert has_local_commits(str(clone)) is True


@pytest.mark.smoke
def test_has_local_commits_no_upstream_returns_false(tmp_path):
    """@{u}..HEAD fails with no upstream → safe False default."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-b", "main", cwd=repo)
    _git_config(repo)
    (repo / "README.md").write_text("hi")
    _git("add", ".", cwd=repo)
    _git("commit", "-m", "init", cwd=repo)
    assert has_local_commits(str(repo)) is False


# ---------------------------------------------------------------------------
# git_fetch_bare
# ---------------------------------------------------------------------------

def _make_bare(upstream: Path, dest: Path) -> Path:
    """Bare clone with fetch refspec configured (as owm init would do)."""
    subprocess.run(["git", "clone", "--bare", str(upstream), str(dest)],
                   check=True, capture_output=True)
    # git clone --bare does not set a fetch refspec; without one, fetching only
    # updates FETCH_HEAD, not refs/heads/*. owm init is responsible for setting this.
    subprocess.run(
        ["git", "config", "remote.origin.fetch", "+refs/heads/*:refs/heads/*"],
        cwd=str(dest), check=True, capture_output=True,
    )
    return dest


@pytest.mark.smoke
def test_git_fetch_bare_returns_true_when_upstream_updated(tmp_path):
    up = _upstream(tmp_path)
    bare = _make_bare(up, tmp_path / "repo.git")
    _commit(up, "new.txt", "new", "new upstream commit")
    assert git_fetch_bare(str(bare)) is True


@pytest.mark.smoke
def test_git_fetch_bare_returns_false_when_nothing_new(tmp_path):
    up = _upstream(tmp_path)
    bare = _make_bare(up, tmp_path / "repo.git")
    assert git_fetch_bare(str(bare)) is False


# ---------------------------------------------------------------------------
# git_fast_forward
# ---------------------------------------------------------------------------

@pytest.mark.smoke
def test_git_fast_forward_advances_head_to_upstream(tmp_path):
    up = _upstream(tmp_path)
    clone = _clone(up, tmp_path / "clone")
    _commit(up, "new.txt", "new", "upstream new")
    _git("fetch", "origin", cwd=clone)
    old_head = _current_head(clone)
    git_fast_forward(str(clone))
    assert _current_head(clone) != old_head
    assert read_repo_state(str(clone))["status"] == "clean"


# ---------------------------------------------------------------------------
# git_rebase
# ---------------------------------------------------------------------------

@pytest.mark.smoke
def test_git_rebase_replays_local_commit_onto_upstream(tmp_path):
    up = _upstream(tmp_path)
    clone = _clone(up, tmp_path / "clone")
    _commit(up, "upstream.txt", "up", "upstream commit")
    _git("fetch", "origin", cwd=clone)
    _commit(clone, "local.txt", "local", "local commit")
    assert read_repo_state(str(clone))["status"] == "diverged"
    git_rebase(str(clone))
    # After rebase: local commit replayed on top of upstream → ahead by 1
    state = read_repo_state(str(clone))
    assert state["status"] == "ahead"
    assert state["ahead_by"] == 1


# ---------------------------------------------------------------------------
# git_push
# ---------------------------------------------------------------------------

@pytest.mark.smoke
def test_git_push_clears_ahead_status(tmp_path):
    # Must push to a bare upstream — git refuses pushes to a checked-out branch
    up = _bare_upstream(tmp_path)
    clone = _clone(up, tmp_path / "clone")
    _commit(clone, "local.txt", "local", "local commit")
    assert read_repo_state(str(clone))["status"] == "ahead"
    git_push(str(clone))
    assert read_repo_state(str(clone))["status"] == "clean"


# ---------------------------------------------------------------------------
# git_reset_hard
# ---------------------------------------------------------------------------

@pytest.mark.smoke
def test_git_reset_hard_clears_dirty_state(tmp_path):
    up = _upstream(tmp_path)
    clone = _clone(up, tmp_path / "clone")
    (clone / "README.md").write_text("modified")
    _git("add", ".", cwd=clone)
    assert read_repo_state(str(clone))["status"] == "dirty"
    git_reset_hard(str(clone))
    assert read_repo_state(str(clone))["status"] == "clean"


@pytest.mark.smoke
def test_git_reset_hard_removes_untracked_files(tmp_path):
    up = _upstream(tmp_path)
    clone = _clone(up, tmp_path / "clone")
    untracked = clone / "garbage.txt"
    untracked.write_text("junk")
    assert untracked.exists()
    git_reset_hard(str(clone))
    assert not untracked.exists()
    assert read_repo_state(str(clone))["status"] == "clean"


@pytest.mark.smoke
def test_git_reset_hard_discards_local_commits(tmp_path):
    up = _upstream(tmp_path)
    clone = _clone(up, tmp_path / "clone")
    _commit(clone, "local.txt", "local", "local commit")
    assert has_local_commits(str(clone)) is True
    git_reset_hard(str(clone))
    assert has_local_commits(str(clone)) is False


# ---------------------------------------------------------------------------
# git_run — failure wrapping
# ---------------------------------------------------------------------------

@pytest.mark.smoke
def test_git_run_wraps_failure_as_owm_error(tmp_path):
    """A failing git command (check=True) raises OwmError(GIT_COMMAND_FAILED),
    not a bare CalledProcessError, so the CLI prints a clean message. git's
    stderr rides home in .extra for structured consumers (notifications)."""
    up = _upstream(tmp_path)
    clone = _clone(up, tmp_path / "clone")
    with pytest.raises(OwmError) as ei:
        git_run(["merge", "--ff-only", "origin/does-not-exist"], cwd=str(clone))
    assert ei.value.code == GIT_COMMAND_FAILED
    assert ei.value.extra.get("stderr")


@pytest.mark.smoke
def test_git_run_passthrough_when_check_false(tmp_path):
    """check=False callers keep inspecting returncode — no wrapping."""
    up = _upstream(tmp_path)
    clone = _clone(up, tmp_path / "clone")
    r = git_run(["merge", "--ff-only", "origin/does-not-exist"], cwd=str(clone), check=False)
    assert r.returncode != 0


@pytest.mark.smoke
def test_git_fast_forward_surfaces_stale_index_lock(tmp_path):
    """The incident: a stale index.lock blocking the ff is surfaced as a clean
    OwmError whose message names the lock, instead of a raw traceback."""
    up = _upstream(tmp_path)
    clone = _clone(up, tmp_path / "clone")
    _commit(up, "next.txt", "next", "advance upstream")
    _git("fetch", "origin", cwd=clone)  # clone now behind origin/main
    (clone / ".git" / "index.lock").write_text("")
    with pytest.raises(OwmError) as ei:
        git_fast_forward(str(clone))
    assert ei.value.code == GIT_COMMAND_FAILED
    assert "index.lock" in ei.value.args[0]
