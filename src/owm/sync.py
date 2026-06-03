import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone

from owm.config import parse_instance_config, parse_workspace_config
from owm.errors import OwmError, DIVERGED, NOT_OWNED, SHARED_REPO, DIRTY_WORKTREE, FETCH_TIMEOUT
from owm.oplog import workspace_log
from owm.worktrees import resolve_worktree_path


# ---------------------------------------------------------------------------
# Git I/O helpers
# ---------------------------------------------------------------------------

def git_run(args: list[str], cwd: str, *, check: bool = True, timeout: int | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), check=check,
                          capture_output=True, text=True, timeout=timeout)


def read_repo_state(worktree_path: str) -> dict:
    """Return {"status": dirty|diverged|behind|ahead|clean, ...} from real git state."""
    r = git_run(["status", "--porcelain"], cwd=worktree_path, check=False)
    if r.returncode != 0:
        return {"status": "clean"}
    if r.stdout.strip():
        return {"status": "dirty"}
    lr = git_run(["rev-list", "--count", "--left-right", "HEAD...@{u}"],
                 cwd=worktree_path, check=False)
    if lr.returncode != 0:
        return {"status": "clean"}
    parts = lr.stdout.strip().split()
    ahead  = int(parts[0]) if parts else 0
    behind = int(parts[1]) if len(parts) > 1 else 0
    if ahead and behind:
        return {"status": "diverged", "ahead_by": ahead, "behind_by": behind}
    if behind:
        return {"status": "behind", "behind_by": behind}
    if ahead:
        return {"status": "ahead", "ahead_by": ahead}
    return {"status": "clean"}


def has_local_commits(worktree_path: str) -> bool:
    r = git_run(["rev-list", "--count", "@{u}..HEAD"], cwd=worktree_path, check=False)
    return r.returncode == 0 and int(r.stdout.strip() or "0") > 0


def git_fetch_bare(bare_path: str, *, branches: list[str] | None = None, timeout: int = 60) -> bool:
    """Fetch a bare repo; returns True if any branch refs were updated.

    Pass `branches` to fetch only specific refs instead of all remote branches.
    FETCH_HEAD always appears in --porcelain output even when nothing changed,
    so we filter it out and only count real ref updates.

    stderr is not captured so git's progress output streams to the terminal.
    Raises OwmError(FETCH_TIMEOUT) if the fetch exceeds `timeout` seconds.
    """
    if branches:
        refspecs = [f"+refs/heads/{b}:refs/heads/{b}" for b in branches]
        cmd = ["git", "fetch", "--update-head-ok", "--porcelain", "origin", *refspecs]
    else:
        cmd = ["git", "fetch", "--prune", "--update-head-ok", "--porcelain", "origin"]
    try:
        r = subprocess.run(
            cmd,
            cwd=str(bare_path),
            stdout=subprocess.PIPE,
            stderr=None,  # inherited — git progress streams to terminal
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise OwmError(f"fetch timed out after {timeout}s", code=FETCH_TIMEOUT)
    if r.returncode != 0:
        return False
    ref_lines = [l for l in r.stdout.splitlines() if "FETCH_HEAD" not in l]
    return bool(ref_lines)


def git_current_hash(path: str) -> str:
    return git_run(["rev-parse", "HEAD"], cwd=path).stdout.strip()


def git_fast_forward(worktree_path: str) -> None:
    git_run(["pull", "--ff-only"], cwd=worktree_path)


def git_rebase(worktree_path: str) -> None:
    git_run(["rebase", "@{u}"], cwd=worktree_path)


def git_push(worktree_path: str) -> None:
    # `git push` has no --ff-only flag (that's a pull/merge option); git rejects it with
    # "unknown option". A plain push already refuses non-fast-forward updates by default
    # unless --force is given, which is exactly the ff-only safety we want.
    git_run(["push", "origin", "HEAD"], cwd=worktree_path)


def branch_exists_on_origin(bare_path: str, branch: str) -> bool:
    """Return True if the branch ref exists in a bare repo (i.e. has been fetched)."""
    r = git_run(["rev-parse", "--verify", f"refs/heads/{branch}"],
                cwd=bare_path, check=False)
    return r.returncode == 0


def git_reset_hard(worktree_path: str) -> None:
    has_upstream = git_run(
        ["rev-parse", "--abbrev-ref", "@{u}"], cwd=worktree_path, check=False
    ).returncode == 0
    target = "@{u}" if has_upstream else "HEAD"
    git_run(["reset", "--hard", target], cwd=worktree_path)
    git_run(["clean", "-fd"], cwd=worktree_path)


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


def _collect_active_branches(workspace_root: str) -> dict:
    """Return {repo_name: {branch, ...}} by scanning all instance tomls."""
    active: dict = {}
    instances_dir = os.path.join(workspace_root, "instances")
    if not os.path.isdir(instances_dir):
        return active
    for entry in os.scandir(instances_dir):
        if not entry.is_dir():
            continue
        toml_path = os.path.join(entry.path, "instance.toml")
        if not os.path.exists(toml_path):
            continue
        try:
            with open(toml_path) as f:
                conf = parse_instance_config(f.read())
            for repo_name, spec in conf.repos.items():
                active.setdefault(repo_name, set()).add(spec.branch)
        except Exception:
            pass
    return active


def fetch_active_branches(workspace_root: str) -> dict:
    """Fetch each repo's bare clone, limited to branches active in instances.

    The single orchestrator shared by the CLI, MCP, and dashboard: reads the
    workspace config, fetches only the active branches per repo (skipping repos
    with no bare clone), records fetch timestamps + audit log, and returns
    per-repo outcomes plus the workspace-level fetch policy result. Adapters
    render `repos`/`configured`; they no longer own the fetch loop.
    """
    toml_path = os.path.join(workspace_root, "workspace.toml")
    with open(toml_path) as f:
        ws_conf = parse_workspace_config(f.read())
    repos = list(ws_conf.repos.keys())
    active = _collect_active_branches(workspace_root)

    records = []
    repos_with_updates = []
    unreachable = []
    for name in repos:
        bare_path = os.path.join(workspace_root, "_repos", f"{name}.git")
        if not os.path.isdir(bare_path):
            continue
        branches = sorted(active.get(name, []))
        try:
            updated = git_fetch_bare(bare_path, branches=branches or None)
        except OwmError as e:
            unreachable.append(name)
            records.append({"name": name, "branches": branches,
                            "status": "unreachable", "error": e.args[0], "code": e.code})
            continue
        records.append({"name": name, "branches": branches,
                        "status": "updated" if updated else "up_to_date"})
        if updated:
            repos_with_updates.append(name)

    result = fetch_workspace(repos=repos, repos_with_updates=repos_with_updates,
                             unreachable_repos=unreachable)

    fetched = [r for r in repos if r not in unreachable]
    if fetched:
        ts_path = os.path.join(workspace_root, "_fetch_timestamps.json")
        existing = {}
        if os.path.exists(ts_path):
            try:
                with open(ts_path) as f:
                    existing = json.load(f)
            except Exception:
                pass
        now = datetime.now(timezone.utc).isoformat()
        existing.update({r: now for r in fetched})
        with open(ts_path, "w") as f:
            json.dump(existing, f, indent=2)

    for name in repos:
        if name in unreachable:
            workspace_log(workspace_root, "fetch", repo=name, status="unreachable")
        elif name in repos_with_updates:
            workspace_log(workspace_root, "fetch", repo=name, status="updated")
        else:
            workspace_log(workspace_root, "fetch", repo=name, status="up_to_date")

    return {
        "configured": repos,
        "repos": records,
        "events": result.events_emitted,
        "warnings": result.warnings,
    }


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


def sync_worktrees(instance, workspace_root, *, repo=None, rebase=False) -> dict:
    """Gather repo states, decide per-repo sync actions, and apply them.

    The orchestrator shared by `owm sync` (via MCP) and the dashboard sync
    button: read the instance config, build repo states, run the sync_instance
    policy, then fast-forward or rebase each worktree the policy selected.
    Returns {"repos": <decisions>}.
    """
    toml_path = os.path.join(workspace_root, "instances", instance, "instance.toml")
    with open(toml_path) as f:
        conf = parse_instance_config(f.read())

    repo_states = {}
    for name, spec in conf.repos.items():
        if repo and name != repo:
            continue
        wt = resolve_worktree_path(name, spec.branch, spec.shared, workspace_root, instance)
        repo_states[name] = (
            {"status": "clean", "shared": True} if spec.shared
            else read_repo_state(wt.path)
        )

    decisions = sync_instance(instance=instance, repo_states=repo_states,
                              rebase=rebase, repo=repo)

    for name, decision in decisions.items():
        spec = conf.repos.get(name)
        if not spec or spec.shared:
            continue
        wt = resolve_worktree_path(name, spec.branch, spec.shared, workspace_root, instance)
        if decision["status"] == "fast-forwarded":
            git_fast_forward(wt.path)
        elif decision["status"] == "rebased":
            git_rebase(wt.path)

    return {"repos": decisions}


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


def push_worktree(instance, workspace_root, *, repo) -> dict:
    """Push one repo's branch to origin (ff-only).

    The orchestrator shared by `owm push` (via MCP) and the dashboard push
    button: read the instance config and repo state, run the push_instance
    policy (which raises OwmError on shared/unowned/diverged), then push the
    worktree. Returns the push result with the branch name; raises OwmError
    for the caller to shape.
    """
    toml_path = os.path.join(workspace_root, "instances", instance, "instance.toml")
    with open(toml_path) as f:
        conf = parse_instance_config(f.read())

    spec = conf.repos[repo]
    wt = resolve_worktree_path(repo, spec.branch, spec.shared, workspace_root, instance)
    state = read_repo_state(wt.path)
    branch_status = state["status"] if state["status"] in ("diverged", "ahead") else None

    result = push_instance(
        instance,
        repo=repo,
        shared=spec.shared,
        owned=not spec.readonly,
        branch_status=branch_status,
    )

    git_push(wt.path)
    result["branch"] = spec.branch
    return result


def pull_base_instance(
    instance: str,
    workspace_root: str,
    *,
    repo: str | None = None,
) -> dict:
    """Merge origin/<base> into each feature repo's local worktree.

    Pre-flight checks all targets are clean before touching anything.
    On merge conflict: aborts cleanly and reports conflicting files.
    """
    toml_path = os.path.join(workspace_root, "instances", instance, "instance.toml")
    with open(toml_path) as f:
        conf = parse_instance_config(f.read())

    targets = {
        name: spec for name, spec in conf.repos.items()
        if spec.base and not spec.shared and (repo is None or name == repo)
    }

    if not targets:
        return {"results": {}, "note": "no feature repos with base configured"}

    for name, spec in targets.items():
        wt = resolve_worktree_path(name, spec.branch, False, workspace_root, instance)
        r = git_run(["status", "--porcelain"], cwd=wt.path, check=False)
        if r.returncode == 0 and r.stdout.strip():
            raise OwmError(f"{name} has uncommitted changes — stash or commit first", code=DIRTY_WORKTREE)

    results = {}
    for name, spec in targets.items():
        wt = resolve_worktree_path(name, spec.branch, False, workspace_root, instance)
        r = git_run(["merge", "--no-edit", f"origin/{spec.base}"], cwd=wt.path, check=False)
        if r.returncode == 0:
            already = "Already up to date." in r.stdout
            results[name] = {"status": "up_to_date" if already else "merged", "base": spec.base}
        else:
            cf = git_run(["diff", "--name-only", "--diff-filter=U"], cwd=wt.path, check=False)
            conflicts = cf.stdout.strip().splitlines() if cf.returncode == 0 else []
            git_run(["merge", "--abort"], cwd=wt.path, check=False)
            results[name] = {"status": "conflict", "base": spec.base, "conflicts": conflicts}

    return {"results": results}


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
                raise OwmError(f"{name} has uncommitted changes; use --force",
                               code=DIRTY_WORKTREE, hint="use --force to discard uncommitted changes")
            else:
                branch = name
                result[name] = {
                    "status": "reset",
                    "to": f"origin/{branch}",
                    "discarded_changes": state.get("dirty", False),
                }
        return result

    if dirty and not force:
        raise OwmError(f"{repo!r} has uncommitted changes; use --force to discard",
                       code=DIRTY_WORKTREE, hint="use --force to discard uncommitted changes")

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
