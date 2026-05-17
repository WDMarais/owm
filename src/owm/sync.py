from dataclasses import dataclass, field
from datetime import datetime, timezone

from owm.errors import OwmError, DIVERGED, NOT_OWNED, SHARED_REPO, DIRTY_WORKTREE


@dataclass
class FetchResult:
    fetched: list
    skipped: list
    warnings: dict
    events_emitted: list
    shared_worktrees_fast_forwarded: list
    shared_worktree_hashes_logged: dict
    blocked_worktrees: dict
    db_snapshots_taken: list


@dataclass
class Checkpoint:
    timestamp: str
    hashes: dict
    db_snapshot: str
    manual: bool
    note: str | None = None


@dataclass
class RollbackResult:
    worktrees_reverted: bool
    db_restored: bool
    checkpoint_used: dict
    changes_since: dict | None = None


def fetch_workspace(
    repos: list[str],
    repos_with_updates: list[str],
    *,
    shared_worktrees: dict | None = None,
    unreachable_repos: list[str] | None = None,
    instances_on_shared: list[str] | None = None,
) -> FetchResult:
    unreachable = set(unreachable_repos or [])
    fetched = [r for r in repos_with_updates if r not in unreachable]
    skipped = [r for r in repos if r not in repos_with_updates and r not in unreachable]
    warnings = {r: f"{r} unreachable" for r in unreachable}

    fast_forwarded = []
    hashes_logged = {}
    blocked = {}
    db_snapshots = []

    for key, info in (shared_worktrees or {}).items():
        if info.get("has_local_commits"):
            blocked[key] = {"reason": "local_commits"}
            continue
        if info.get("has_migration") and instances_on_shared:
            db_snapshots.extend(instances_on_shared)
        fast_forwarded.append(key)
        if "current_hash" in info:
            hashes_logged[key] = info["current_hash"]

    return FetchResult(
        fetched=fetched,
        skipped=skipped,
        warnings=warnings,
        events_emitted=["fetch_completed"],
        shared_worktrees_fast_forwarded=fast_forwarded,
        shared_worktree_hashes_logged=hashes_logged,
        blocked_worktrees=blocked,
        db_snapshots_taken=db_snapshots,
    )


def sync_instance(
    instance: str,
    repo_states: dict,
    *,
    rebase: bool = False,
    repo: str | None = None,
) -> dict:
    result = {}
    for name, state in repo_states.items():
        if repo and name != repo:
            continue
        status = state.get("status")
        if state.get("shared"):
            result[name] = {"status": "skipped", "reason": "shared worktree — use owm fetch"}
        elif status == "dirty":
            result[name] = {"status": "skipped", "reason": "uncommitted changes"}
        elif status == "diverged":
            if rebase:
                result[name] = {"status": "rebased"}
            else:
                result[name] = {"status": "diverged", "hint": "run owm sync --rebase to rebase"}
        elif status == "behind":
            result[name] = {
                "status": "fast-forwarded",
                "from": "HEAD~" + str(state.get("behind_by", 1)),
                "to": "origin/" + name,
            }
        else:
            result[name] = {"status": "skipped", "reason": "nothing to do"}
    return result


def push_instance(
    instance: str,
    *,
    repo: str | None = None,
    all_repos: bool = False,
    repo_states: dict | None = None,
    branch: str | None = None,
    branch_status: str | None = None,
    owned: bool = True,
    shared: bool = False,
) -> dict:
    if all_repos and repo_states is not None:
        result = {}
        for name, state in repo_states.items():
            if state.get("shared"):
                result[name] = {"status": "skipped", "reason": "shared repo — push manually"}
            elif not state.get("owned", True):
                result[name] = {"status": "skipped", "reason": "not owned"}
            elif state.get("status") == "ahead":
                result[name] = {"status": "pushed", "repo": name}
            else:
                result[name] = {"status": "skipped", "reason": "nothing to push"}
        return result

    if shared:
        raise OwmError(
            f"[SHARED_REPO] {repo or branch!r} is a shared branch; "
            f"run: git -C _shared/{repo}/... push origin {branch or 'HEAD'}",
            code=SHARED_REPO,
        )
    if not owned:
        raise OwmError(f"repo {repo!r} is not owned by {instance!r}", code=NOT_OWNED)
    if branch_status == "diverged":
        raise OwmError(f"branch has diverged from origin; rebase before pushing", code=DIVERGED)

    return {"status": "pushed", "repo": repo}


def reset_instance(
    instance: str,
    repo: str | None = None,
    *,
    dirty: bool = False,
    force: bool = False,
    has_local_commits: bool = False,
    all_repos: bool = False,
    repo_states: dict | None = None,
) -> dict:
    if all_repos and repo_states is not None:
        result = {}
        for name, state in repo_states.items():
            if state.get("shared"):
                result[name] = {"status": "skipped", "reason": "shared worktree — skip"}
            elif state.get("dirty") and not force:
                raise OwmError(f"{name} has uncommitted changes; use --force", code=DIRTY_WORKTREE)
            else:
                branch = name
                result[name] = {
                    "status": "reset",
                    "to": f"origin/{branch}",
                    "discarded_changes": state.get("dirty", False),
                }
        return result

    if dirty and not force:
        raise OwmError(f"{repo!r} has uncommitted changes; use --force to discard", code=DIRTY_WORKTREE)

    branch = repo or "HEAD"
    out = {"status": "reset", "to": f"origin/{branch}"}
    if dirty and force:
        out["discarded_changes"] = True
    if has_local_commits:
        out["warning"] = f"local commits on {branch!r} were discarded; origin/{branch} is now HEAD"
    return out


def record_checkpoint(
    instance: str,
    repo_hashes: dict[str, str],
    db_snapshot_path: str,
    manual: bool,
    note: str | None = None,
) -> Checkpoint:
    return Checkpoint(
        timestamp=datetime.now(timezone.utc).isoformat(),
        hashes=repo_hashes,
        db_snapshot=db_snapshot_path,
        manual=manual,
        note=note,
    )


def rollback_to_checkpoint(
    instance: str,
    checkpoint: dict,
    *,
    current_hashes: dict | None = None,
) -> RollbackResult:
    changes_since = None
    if current_hashes is not None:
        changes_since = {
            repo: {"from": checkpoint["hashes"].get(repo), "to": current}
            for repo, current in current_hashes.items()
            if current != checkpoint["hashes"].get(repo)
        }
    return RollbackResult(
        worktrees_reverted=True,
        db_restored=True,
        checkpoint_used=checkpoint,
        changes_since=changes_since,
    )
