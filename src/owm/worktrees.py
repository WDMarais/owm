import os
import subprocess
from dataclasses import dataclass

from owm.errors import OwmError, NOT_OWNED, SHARED_REPO, BRANCH_NOT_FOUND


@dataclass
class WorktreeConfig:
    path: str
    per_instance: bool
    shared: bool


@dataclass
class WorktreeResult:
    action: str   # "linked" | "created"
    path: str


@dataclass
class PushResult:
    status: str


@dataclass
class WarningResult:
    warning: bool
    message: str = ""


@dataclass
class EditResult:
    allowed: bool


def resolve_worktree_path(
    repo: str,
    branch: str,
    shared: bool,
    workspace_root: str,
    instance_name: str,
) -> WorktreeConfig:
    if shared:
        path = os.path.join(workspace_root, "_shared", repo, branch)
        return WorktreeConfig(path=path, per_instance=False, shared=True)
    path = os.path.join(workspace_root, "instances", instance_name, repo)
    return WorktreeConfig(path=path, per_instance=True, shared=False)


def _branch_exists(bare_repo: str, branch: str) -> bool:
    r = subprocess.run(
        ["git", "rev-parse", "--verify", f"refs/heads/{branch}"],
        cwd=bare_repo, capture_output=True,
    )
    return r.returncode == 0


def _origin_branch_exists(bare_repo: str, branch: str) -> bool:
    r = subprocess.run(
        ["git", "rev-parse", "--verify", f"refs/remotes/origin/{branch}"],
        cwd=bare_repo, capture_output=True,
    )
    return r.returncode == 0


def _git_worktree_add(bare_repo: str, path: str, branch: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.run(
        ["git", "worktree", "add", path, branch],
        cwd=bare_repo, check=True, capture_output=True,
    )


def _git_worktree_add_new(bare_repo: str, path: str, branch: str, base: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.run(
        ["git", "worktree", "add", "-b", branch, path, base],
        cwd=bare_repo, check=True, capture_output=True,
    )


def create_worktree(
    repo: str,
    branch: str,
    shared: bool,
    workspace_root: str,
    instance_name: str,
    *,
    base: str | None = None,
    assert_exists: bool = False,
    create: bool = False,
) -> WorktreeResult:
    cfg = resolve_worktree_path(repo, branch, shared, workspace_root, instance_name)
    bare_repo = os.path.join(workspace_root, "_repos", f"{repo}.git")

    # Shared repos always check out an existing branch — skip branch-intent checks
    if shared:
        if os.path.exists(cfg.path):
            return WorktreeResult(action="linked", path=cfg.path)
        _git_worktree_add(bare_repo, cfg.path, branch)
        return WorktreeResult(action="linked", path=cfg.path)

    if assert_exists and create:
        raise OwmError(
            f"repo {repo!r}: +exists and +create are mutually exclusive",
            code="INVALID_REPO_SPEC",
        )

    if os.path.exists(cfg.path):
        return WorktreeResult(action="linked", path=cfg.path)

    # A branch that already exists is checked out, not created — no base needed.
    # Local takes precedence; otherwise seed a local branch from origin (the
    # "check out a colleague's pushed branch" case). The base is only required
    # to create a branch that exists in neither place.
    if _branch_exists(bare_repo, branch):
        _git_worktree_add(bare_repo, cfg.path, branch)
        return WorktreeResult(action="created", path=cfg.path)
    if _origin_branch_exists(bare_repo, branch):
        _git_worktree_add_new(bare_repo, cfg.path, branch, f"origin/{branch}")
        return WorktreeResult(action="created", path=cfg.path)

    # Branch exists nowhere yet.
    if create:
        if not base:
            raise OwmError(
                f"repo {repo!r}: +create requires a base branch "
                f"(branch {branch!r} not found locally or on origin)",
                code=BRANCH_NOT_FOUND,
            )
        _git_worktree_add_new(bare_repo, cfg.path, branch, base)
        return WorktreeResult(action="created", path=cfg.path)
    if assert_exists:
        raise OwmError(
            f"repo {repo!r}: +exists asserted but branch {branch!r} not found locally or on origin "
            f"— check for a typo or push the branch first",
            code=BRANCH_NOT_FOUND,
        )
    raise OwmError(
        f"repo {repo!r}: branch {branch!r} not found locally or on origin — "
        f"add +create to create it from base",
        code=BRANCH_NOT_FOUND,
    )


def remove_worktree(bare_repo: str, worktree_path: str) -> None:
    """Deregister and delete a worktree. Silently skips if path doesn't exist."""
    if os.path.exists(worktree_path):
        subprocess.run(
            ["git", "worktree", "remove", "--force", worktree_path],
            cwd=bare_repo, check=True, capture_output=True,
        )


def push_branch(
    instance: str,
    repo: str,
    branch: str,
    *,
    readonly: bool,
    shared: bool,
    override: bool,
    override_allowed_in_config: bool = True,
) -> PushResult:
    if shared:
        raise OwmError(
            f"[{SHARED_REPO}] {repo!r} is a shared worktree — push via git directly: "
            f"cd _shared/{repo}/{branch} && git push",
            code=SHARED_REPO,
        )
    if readonly and not (override and override_allowed_in_config):
        raise OwmError(
            f"[{NOT_OWNED}] {repo!r} in {instance!r} is not configured as owned; "
            "push refused",
            code=NOT_OWNED,
        )
    return PushResult(status="pushed")


def check_shared_commit_warning(
    repo: str,
    branch: str,
    shared: bool,
    has_new_commit: bool,
) -> WarningResult:
    if shared and has_new_commit:
        return WarningResult(
            warning=True,
            message=f"commit in shared worktree {repo!r} is visible to all instances on {branch!r}",
        )
    return WarningResult(warning=False)


def check_edit_allowed(readonly: bool) -> EditResult:
    # readonly restricts push only; local edits and commits are always permitted
    return EditResult(allowed=True)
