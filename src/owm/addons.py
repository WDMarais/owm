import os


def resolve_addons_path(
    workspace_repos: dict,
    instance_repos: dict,
    workspace_root: str,
    instance_name: str,
    instances_dir: str,
) -> list[str]:
    # Across repos: reverse workspace declaration order (base→specific; last-declared wins).
    # Within a repo's addons_paths: preserve declaration order (first-declared = highest priority).
    result = []
    for repo_name in reversed(list(workspace_repos.keys())):
        meta = workspace_repos[repo_name]
        if not meta.get("has_addons", False):
            continue
        if repo_name not in instance_repos:
            continue

        inst_repo = instance_repos[repo_name]
        shared = inst_repo.get("shared", False)
        branch = inst_repo.get("branch", "")
        addons_paths = meta.get("addons_paths", ["."])

        if shared:
            base = os.path.join(workspace_root, "_shared", repo_name, branch)
        else:
            base = os.path.join(workspace_root, instances_dir, instance_name, repo_name)

        for ap in addons_paths:
            if ap == ".":
                result.append(base)
            else:
                result.append(os.path.join(base, ap))

    return result
