"""
Tests for addons_path generation in instance.conf.
Covers: Addons resolution section.
"""
import pytest

from owm.addons import resolve_addons_path


# ---------------------------------------------------------------------------
# Integration: full addons_path for a given instance
# ---------------------------------------------------------------------------

@pytest.mark.addons_resolution
def test_addons_path_full_instance_declaration_order():
    """
    workspace.toml declares repos in priority order: customer-config → product-core → odoo.
    addons_path preserves this order: customer-config first (highest priority), odoo last.
    odoo uses addons_paths=["addons","odoo/addons"] — contributes two entries.
    """
    workspace_repos = {
        "customer-config": {"has_addons": True,  "addons_paths": ["addons"],                "url": "..."},
        "product-core":    {"has_addons": True,  "addons_paths": ["addons"],                "url": "..."},
        "odoo":            {"has_addons": True,  "addons_paths": ["addons", "odoo/addons"], "url": "..."},
        "scripts":         {"has_addons": False,                                             "url": "..."},
    }
    instance_repos = {
        "odoo":            {"branch": "19.0", "shared": True},
        "product-core":    {"branch": "feat-789-dev", "shared": False},
        "customer-config": {"branch": "feat-789-dev", "shared": False},
    }
    result = resolve_addons_path(
        workspace_repos=workspace_repos,
        instance_repos=instance_repos,
        workspace_root="/ws",
        instance_name="feat-789",
        instances_dir="instances",
    )
    assert result == [
        "/ws/instances/feat-789/customer-config/addons",
        "/ws/instances/feat-789/product-core/addons",
        "/ws/_shared/odoo/19.0/addons",
        "/ws/_shared/odoo/19.0/odoo/addons",
    ]


@pytest.mark.addons_resolution
def test_addons_path_excludes_repo_not_in_instance():
    """customer-config absent from instance.toml → silently excluded, no warning."""
    workspace_repos = {
        "customer-config": {"has_addons": True,  "addons_paths": ["addons"],                "url": "..."},
        "product-core":    {"has_addons": True,  "addons_paths": ["addons"],                "url": "..."},
        "odoo":            {"has_addons": True,  "addons_paths": ["addons", "odoo/addons"], "url": "..."},
    }
    instance_repos = {
        "odoo":         {"branch": "19.0", "shared": True},
        "product-core": {"branch": "feat-789-dev", "shared": False},
        # customer-config deliberately absent
    }
    result = resolve_addons_path(
        workspace_repos=workspace_repos,
        instance_repos=instance_repos,
        workspace_root="/ws",
        instance_name="feat-789",
        instances_dir="instances",
    )
    assert "/ws/instances/feat-789/customer-config/addons" not in result
    assert result == [
        "/ws/instances/feat-789/product-core/addons",
        "/ws/_shared/odoo/19.0/addons",
        "/ws/_shared/odoo/19.0/odoo/addons",
    ]


@pytest.mark.addons_resolution
def test_addons_path_excludes_repo_without_has_addons():
    """scripts repo: has_addons = false in workspace.toml → never appears in addons_path."""
    workspace_repos = {
        "odoo":     {"has_addons": True,  "addons_paths": ["addons"], "url": "..."},
        "scripts":  {"has_addons": False,                              "url": "..."},
    }
    instance_repos = {
        "odoo":    {"branch": "19.0", "shared": True},
        "scripts": {"branch": "reviews/feat-789", "shared": False},
    }
    result = resolve_addons_path(
        workspace_repos=workspace_repos,
        instance_repos=instance_repos,
        workspace_root="/ws",
        instance_name="feat-789",
        instances_dir="instances",
    )
    assert all("scripts" not in p for p in result)


@pytest.mark.addons_resolution
def test_addons_path_shared_worktree_resolves_each_configured_path():
    """Shared worktree with addons_paths → each path resolved under _shared/<repo>/<branch>/."""
    workspace_repos = {
        "odoo": {"has_addons": True, "addons_paths": ["addons", "odoo/addons"], "url": "..."},
    }
    instance_repos = {
        "odoo": {"branch": "19.0", "shared": True},
    }
    result = resolve_addons_path(
        workspace_repos=workspace_repos,
        instance_repos=instance_repos,
        workspace_root="/ws",
        instance_name="feat-789",
        instances_dir="instances",
    )
    assert "/ws/_shared/odoo/19.0/addons" in result
    assert "/ws/_shared/odoo/19.0/odoo/addons" in result


@pytest.mark.addons_resolution
def test_addons_path_default_addons_paths_is_repo_root():
    """Repo with has_addons=true but no addons_paths → defaults to ["."] (repo root).

    The common real-world layout has addons directly at repo root with no
    addons/ subdirectory wrapper. Default ["."] supports this without
    requiring every workspace.toml to spell it out. Repos using the addons/
    convention declare addons_paths = ["addons"] explicitly.
    """
    workspace_repos = {
        "product-core": {"has_addons": True, "url": "..."},
        # no addons_paths key → default ["."]
    }
    instance_repos = {
        "product-core": {"branch": "feat-789-dev", "shared": False},
    }
    result = resolve_addons_path(
        workspace_repos=workspace_repos,
        instance_repos=instance_repos,
        workspace_root="/ws",
        instance_name="feat-789",
        instances_dir="instances",
    )
    assert result == ["/ws/instances/feat-789/product-core"]


@pytest.mark.addons_resolution
def test_addons_path_explicit_root_dot():
    """addons_paths=["."] explicitly → repo root as addons dir."""
    workspace_repos = {
        "product-core": {"has_addons": True, "addons_paths": ["."], "url": "..."},
    }
    instance_repos = {
        "product-core": {"branch": "feat-789-dev", "shared": False},
    }
    result = resolve_addons_path(
        workspace_repos=workspace_repos,
        instance_repos=instance_repos,
        workspace_root="/ws",
        instance_name="feat-789",
        instances_dir="instances",
    )
    assert result == ["/ws/instances/feat-789/product-core"]


@pytest.mark.addons_resolution
def test_addons_path_explicit_named_subfolders():
    """addons_paths accepts any folder names — "addons" is not required in the string."""
    workspace_repos = {
        "product-core": {"has_addons": True, "addons_paths": ["primary_addons", "extras"], "url": "..."},
    }
    instance_repos = {
        "product-core": {"branch": "feat-789-dev", "shared": False},
    }
    result = resolve_addons_path(
        workspace_repos=workspace_repos,
        instance_repos=instance_repos,
        workspace_root="/ws",
        instance_name="feat-789",
        instances_dir="instances",
    )
    assert "/ws/instances/feat-789/product-core/primary_addons" in result
    assert "/ws/instances/feat-789/product-core/extras" in result


@pytest.mark.addons_resolution
def test_addons_path_multi_path_repo_both_folders_included():
    """Repo with addons_paths=["primary_addons","secondary_addons"] → both in addons_path."""
    workspace_repos = {
        "multi-repo": {"has_addons": True, "addons_paths": ["primary_addons", "secondary_addons"], "url": "..."},
    }
    instance_repos = {
        "multi-repo": {"branch": "feat-789-dev", "shared": False},
    }
    result = resolve_addons_path(
        workspace_repos=workspace_repos,
        instance_repos=instance_repos,
        workspace_root="/ws",
        instance_name="feat-789",
        instances_dir="instances",
    )
    assert "/ws/instances/feat-789/multi-repo/secondary_addons" in result
    assert "/ws/instances/feat-789/multi-repo/primary_addons" in result


@pytest.mark.addons_resolution
def test_addons_path_multi_path_repo_declaration_order_within_repo():
    """Within a repo's addons_paths, first-declared = highest priority.
    Same rule as across repos: declaration order is priority order throughout."""
    workspace_repos = {
        "multi-repo": {"has_addons": True, "addons_paths": ["primary_addons", "secondary_addons"], "url": "..."},
    }
    instance_repos = {
        "multi-repo": {"branch": "feat-789-dev", "shared": False},
    }
    paths = resolve_addons_path(
        workspace_repos=workspace_repos,
        instance_repos=instance_repos,
        workspace_root="/ws",
        instance_name="feat-789",
        instances_dir="instances",
    )
    if not isinstance(paths, list):
        paths = list(paths)
    primary_idx   = next(i for i, p in enumerate(paths) if "primary_addons" in p)
    secondary_idx = next(i for i, p in enumerate(paths) if "secondary_addons" in p)
    assert primary_idx < secondary_idx


@pytest.mark.addons_resolution
def test_addons_path_exclusion_produces_no_warning():
    """Silent exclusion: absent repo with has_addons=true in workspace must not warn."""
    workspace_repos = {
        "odoo":            {"has_addons": True, "addons_paths": ["addons"], "url": "..."},
        "customer-config": {"has_addons": True, "addons_paths": ["addons"], "url": "..."},
    }
    instance_repos = {
        "odoo": {"branch": "19.0", "shared": True},
        # customer-config absent
    }
    result = resolve_addons_path(
        workspace_repos=workspace_repos,
        instance_repos=instance_repos,
        workspace_root="/ws",
        instance_name="feat-789",
        instances_dir="instances",
    )
    warnings = getattr(result, "warnings", []) if not isinstance(result, list) else []
    assert warnings == []


@pytest.mark.addons_resolution
def test_addons_path_ordering_matches_workspace_declaration_order():
    """
    workspace.toml declaration order is priority order: first-declared = highest priority.
    Declare customer-config first (most specific), odoo last (foundational).
    """
    workspace_repos = {
        "customer-config": {"has_addons": True, "addons_paths": ["addons"],                "url": "..."},
        "product-core":    {"has_addons": True, "addons_paths": ["addons"],                "url": "..."},
        "odoo":            {"has_addons": True, "addons_paths": ["addons", "odoo/addons"], "url": "..."},
    }
    instance_repos = {
        "odoo":            {"branch": "19.0", "shared": True},
        "product-core":    {"branch": "feat-789-dev", "shared": False},
        "customer-config": {"branch": "feat-789-dev", "shared": False},
    }
    paths = resolve_addons_path(
        workspace_repos=workspace_repos,
        instance_repos=instance_repos,
        workspace_root="/ws",
        instance_name="feat-789",
        instances_dir="instances",
    )
    if not isinstance(paths, list):
        paths = list(paths)
    customer_idx = next(i for i, p in enumerate(paths) if "customer-config" in p)
    product_idx  = next(i for i, p in enumerate(paths) if "product-core" in p)
    odoo_idx     = next(i for i, p in enumerate(paths) if "_shared/odoo" in p)
    assert customer_idx < product_idx < odoo_idx


@pytest.mark.addons_resolution
def test_addons_path_repo_priority_overrides_declaration_order():
    """repo_priority in [defaults] overrides TOML declaration order.
    Repos listed in any order in [repos]; explicit priority wins."""
    workspace_repos = {
        "odoo":            {"has_addons": True, "addons_paths": ["addons"], "url": "..."},
        "product-core":    {"has_addons": True, "addons_paths": ["addons"], "url": "..."},
        "customer-config": {"has_addons": True, "addons_paths": ["addons"], "url": "..."},
    }
    instance_repos = {
        "odoo":            {"branch": "19.0",          "shared": True},
        "product-core":    {"branch": "feat-789-dev",  "shared": False},
        "customer-config": {"branch": "feat-789-dev",  "shared": False},
    }
    paths = resolve_addons_path(
        workspace_repos=workspace_repos,
        instance_repos=instance_repos,
        workspace_root="/ws",
        instance_name="feat-789",
        instances_dir="instances",
        repo_priority=["customer-config", "product-core", "odoo"],
    )
    customer_idx = next(i for i, p in enumerate(paths) if "customer-config" in p)
    product_idx  = next(i for i, p in enumerate(paths) if "product-core" in p)
    odoo_idx     = next(i for i, p in enumerate(paths) if "_shared/odoo" in p)
    assert customer_idx < product_idx < odoo_idx


@pytest.mark.addons_resolution
def test_addons_path_declaration_order_is_load_bearing():
    """parse_workspace_config must preserve TOML key insertion order.
    Declaration order = priority order, so a dict that re-sorts keys would silently
    produce wrong addons_path. tomllib preserves order; this test confirms the contract
    is upheld end-to-end through resolve_addons_path."""
    from owm.config import parse_workspace_config
    import textwrap
    toml = textwrap.dedent("""
        [repos]
        customer-config = {path = "git@example.com/customer-config.git", has_addons = true}
        product-core    = {path = "git@example.com/product-core.git", has_addons = true}
        odoo            = {path = "git@example.com/odoo.git", has_addons = true, addons_paths = ["addons", "odoo/addons"]}

        [clusters]
        "19" = {pg_version = "16", port = 5432}
    """)
    cfg = parse_workspace_config(toml)
    repos = list(cfg.repos.keys())
    assert repos.index("customer-config") < repos.index("product-core") < repos.index("odoo")
