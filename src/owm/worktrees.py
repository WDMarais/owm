import os
from dataclasses import dataclass

from owm.errors import OwmError, NOT_OWNED, SHARED_REPO


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


def create_worktree(
    repo: str,
    branch: str,
    shared: bool,
    workspace_root: str,
    instance_name: str,
) -> WorktreeResult:
    cfg = resolve_worktree_path(repo, branch, shared, workspace_root, instance_name)
    action = "linked" if shared else "created"
    return WorktreeResult(action=action, path=cfg.path)


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
