"""
Tests for addons_path generation in instance.conf.
Covers: Addons resolution section.
"""
import pytest

# TODO: from owm.addons import resolve_addons_path
def resolve_addons_path(*args, **kwargs):
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Integration: full addons_path for a given instance
# ---------------------------------------------------------------------------

@pytest.mark.addons_resolution
def test_addons_path_full_instance_reversed_override_order():
    """
    Repos declared in workspace.toml stability order: odoo → product-core → customer-config.
    addons_path reverses this for override specificity: customer-config → product-core → odoo.
    Odoo shared worktree contributes two entries: addons/ and odoo/addons/.
    """
    workspace_repos = {
        "odoo":            {"has_addons": True,  "url": "..."},
        "product-core":    {"has_addons": True,  "url": "..."},
        "customer-config": {"has_addons": True,  "url": "..."},
        "scripts":         {"has_addons": False, "url": "..."},
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
        "odoo":            {"has_addons": True,  "url": "..."},
        "product-core":    {"has_addons": True,  "url": "..."},
        "customer-config": {"has_addons": True,  "url": "..."},
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
        "odoo":     {"has_addons": True,  "url": "..."},
        "scripts":  {"has_addons": False, "url": "..."},
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
def test_addons_path_shared_worktree_uses_shared_path():
    """Repo present in instance via shared worktree → _shared/<repo>/<branch>/addons."""
    workspace_repos = {
        "odoo": {"has_addons": True, "url": "..."},
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
def test_addons_path_exclusion_produces_no_warning():
    """Silent exclusion: absent repo with has_addons=true in workspace must not warn."""
    workspace_repos = {
        "odoo":            {"has_addons": True, "url": "..."},
        "customer-config": {"has_addons": True, "url": "..."},
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
    # result may be a namedtuple or plain list; assert no warnings either way
    warnings = getattr(result, "warnings", []) if not isinstance(result, list) else []
    assert warnings == []


@pytest.mark.addons_resolution
def test_addons_path_ordering_matches_workspace_declaration_reversed():
    """
    workspace.toml declaration order is the stability axis.
    addons_path must reverse it: last-declared = highest override priority.
    """
    workspace_repos = {
        "odoo":            {"has_addons": True, "url": "..."},  # declared first
        "product-core":    {"has_addons": True, "url": "..."},  # declared second
        "customer-config": {"has_addons": True, "url": "..."},  # declared third
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
# test_addons_path_per_instance_non_shared_path_structure: spec gives the shared path
#   as _shared/<repo>/<branch>/addons but does not state the exact subpath for per-instance
#   worktrees (assumed instances/<name>/<repo>/addons — verify in implementation).
# test_addons_path_workspace_declaration_order_preserved: spec says "declared in stability
#   order" but TOML dict ordering was not guaranteed before Python 3.7; confirm whether
#   workspace.toml parsing preserves insertion order or uses an explicit ordering field.
