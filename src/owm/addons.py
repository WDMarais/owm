import os

from owm.worktrees import resolve_worktree_path


def resolve_addons_path(
    workspace_repos: dict,
    instance_repos: dict,
    workspace_root: str,
    instance_name: str,
    repo_priority: list[str] | None = None,
) -> list[str]:
    # Declaration order is priority order: first = highest priority.
    # repo_priority overrides declaration order when present; otherwise TOML key order is used.
    # Within a repo's addons_paths, same rule applies.
    order = repo_priority if repo_priority else list(workspace_repos.keys())
    result = []
    for repo_name in order:
        if repo_name not in workspace_repos:
            continue
        meta = workspace_repos[repo_name]
        if not meta.get("has_addons", False):
            continue
        if repo_name not in instance_repos:
            continue

        inst_repo = instance_repos[repo_name]
        shared = inst_repo.get("shared", False)
        branch = inst_repo.get("branch", "")
        addons_paths = meta.get("addons_paths", ["."])

        base = resolve_worktree_path(repo_name, branch, shared, workspace_root, instance_name).path

        for ap in addons_paths:
            if ap == ".":
                result.append(base)
            else:
                result.append(os.path.join(base, ap))

    return result
