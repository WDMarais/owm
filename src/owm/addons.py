import os

from owm.worktrees import resolve_worktree_path


def empty_addons_path_message(instance_name: str) -> str:
    """Wording for the empty-addons-path failure, shared by every callsite.

    An instance whose addons_path resolves to empty would get an Odoo config
    that loads no modules — not even `base`, so the server can't start. This is
    never a valid steady state, so generation refuses it loudly rather than
    writing a module-less conf. The usual cause is a workspace.toml that names
    repos but declares `has_addons = true` on none of them (e.g. owm's legacy
    flat `name = "url"` form), so resolution opts every repo out.
    """
    return (
        f"addons_path for {instance_name!r} resolved to empty — the generated Odoo "
        f"config would load no modules (not even base). Declare 'has_addons = true' "
        f"on the contributing repos in workspace.toml (at minimum the odoo repo)."
    )


def resolve_addons_path(
    workspace_repos: dict,
    instance_repos: dict,
    workspace_root: str,
    instance_name: str,
    repo_priority: list[str] | None = None,
) -> list[str]:
    # Declaration order is priority order: first = highest priority.
    # repo_priority states the precedence that matters; any has_addons repo it does
    # not name falls in afterwards in declaration order — so omitting a repo can never
    # silently drop it from addons_path, it only ranks it below the named ones.
    # Within a repo's addons_paths, the same first-wins rule applies.
    if repo_priority:
        order = repo_priority + [r for r in workspace_repos if r not in repo_priority]
    else:
        order = list(workspace_repos.keys())
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
