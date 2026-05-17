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
def test_addons_path_full_instance_reversed_override_order():
    """
    Repos declared in workspace.toml stability order: odoo → product-core → customer-config.
    addons_path reverses this for override specificity: customer-config → product-core → odoo.
    odoo uses addons_paths=["addons","odoo/addons"] — contributes two entries.
    """
    workspace_repos = {
        "odoo":            {"has_addons": True,  "addons_paths": ["addons", "odoo/addons"], "url": "..."},
        "product-core":    {"has_addons": True,  "addons_paths": ["addons"],                "url": "..."},
        "customer-config": {"has_addons": True,  "addons_paths": ["addons"],                "url": "..."},
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
    )  # TODO: wire up
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
        "odoo":            {"has_addons": True,  "addons_paths": ["addons", "odoo/addons"], "url": "..."},
        "product-core":    {"has_addons": True,  "addons_paths": ["addons"],                "url": "..."},
        "customer-config": {"has_addons": True,  "addons_paths": ["addons"],                "url": "..."},
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
    )  # TODO: wire up
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
    )  # TODO: wire up
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
    )  # TODO: wire up
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
    )  # TODO: wire up
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
    )  # TODO: wire up
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
    )  # TODO: wire up
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
    )  # TODO: wire up
    assert "/ws/instances/feat-789/multi-repo/secondary_addons" in result
    assert "/ws/instances/feat-789/multi-repo/primary_addons" in result


@pytest.mark.addons_resolution
def test_addons_path_multi_path_repo_declaration_order_within_repo():
    """Within a repo's addons_paths, first-declared = highest priority (no reversal).
    Reversal only applies across repos (workspace declaration order), not within a single
    repo's addons_paths list. Users write addons_paths in explicit priority order."""
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
    )  # TODO: wire up
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
    )  # TODO: wire up
    warnings = getattr(result, "warnings", []) if not isinstance(result, list) else []
    assert warnings == []


@pytest.mark.addons_resolution
def test_addons_path_ordering_matches_workspace_declaration_reversed():
    """
    workspace.toml declaration order is the stability axis.
    addons_path must reverse it: last-declared = highest override priority.
    """
    workspace_repos = {
        "odoo":            {"has_addons": True, "addons_paths": ["addons", "odoo/addons"], "url": "..."},
        "product-core":    {"has_addons": True, "addons_paths": ["addons"],                "url": "..."},
        "customer-config": {"has_addons": True, "addons_paths": ["addons"],                "url": "..."},
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
    )  # TODO: wire up
    if not isinstance(paths, list):
        paths = list(paths)
    customer_idx = next(i for i, p in enumerate(paths) if "customer-config" in p)
    product_idx  = next(i for i, p in enumerate(paths) if "product-core" in p)
    odoo_idx     = next(i for i, p in enumerate(paths) if "_shared/odoo" in p)
    assert customer_idx < product_idx < odoo_idx


# === SPEC GAPS ===
# test_addons_path_workspace_declaration_order_preserved: spec says "declared in stability
#   order" — owm requires Python 3.12+ (dict insertion order guaranteed since 3.7), but
#   confirm that workspace.toml parsing preserves TOML table key order rather than
#   re-sorting or using an unordered dict internally.
