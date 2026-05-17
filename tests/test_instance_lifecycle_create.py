"""
Tests for instance creation and workspace initialisation.
Covers: Instance lifecycle — create, Workspace init sections.
"""
import pytest

# TODO: from owm.instance import new_instance, create_instance
from owm.workspace import init_workspace

def new_instance(*args, **kwargs):
    raise NotImplementedError

def create_instance(*args, **kwargs):
    raise NotImplementedError


# ---------------------------------------------------------------------------
# owm new — generate instance.toml without materialising
# ---------------------------------------------------------------------------

@pytest.mark.instance_lifecycle_create
def test_new_instance_generates_toml_only():
    """owm new: writes instance.toml, no worktrees, no DB, no ports reserved."""
    result = new_instance(
        name="feat-789",
        repos={"odoo": "19.0:shared", "product-core": "feat-789-dev:dev", "customer-config": "feat-789-dev:dev"},
        workspace_root="/ws",
    )  # TODO: wire up
    assert result.toml_path == "/ws/instances/feat-789/instance.toml"
    assert result.toml_content is not None
    assert result.materialised is False


@pytest.mark.instance_lifecycle_create
def test_new_instance_toml_contains_autofilled_port():
    result = new_instance(
        name="feat-789",
        repos={"odoo": "19.0:shared", "product-core": "feat-789-dev:dev"},
        workspace_root="/ws",
    )  # TODO: wire up
    assert "[server]" in result.toml_content
    assert "http_port" in result.toml_content


@pytest.mark.instance_lifecycle_create
def test_new_instance_toml_contains_autofilled_db_name():
    result = new_instance(
        name="feat-789",
        repos={"odoo": "19.0:shared"},
        workspace_root="/ws",
    )  # TODO: wire up
    assert "[database]" in result.toml_content
    assert "feat-789" in result.toml_content


@pytest.mark.instance_lifecycle_create
def test_new_instance_already_exists_returns_error():
    with pytest.raises(Exception) as exc_info:
        new_instance(
            name="feat-789",
            repos={"odoo": "19.0:shared"},
            workspace_root="/ws",
            already_exists=True,
        )  # TODO: wire up
    assert "ALREADY_EXISTS" in str(exc_info.value)


# ---------------------------------------------------------------------------
# owm create — materialise from instance.toml
# ---------------------------------------------------------------------------

@pytest.mark.instance_lifecycle_create
def test_create_instance_materialises_all_resources():
    """Fresh create: worktrees created, DB cloned, port reserved, nginx block written, odoo.conf generated."""
    result = create_instance(
        name="feat-789",
        workspace_root="/ws",
        instance_exists=False,
    )  # TODO: wire up
    assert result.worktrees_created is True
    assert result.db_created is True
    assert result.port_reserved is True
    assert result.nginx_block_written is True
    assert result.odoo_conf_generated is True


@pytest.mark.instance_lifecycle_create
def test_create_instance_idempotent_when_unchanged():
    """Instance already exists and toml unchanged → all steps skipped."""
    result = create_instance(
        name="feat-789",
        workspace_root="/ws",
        instance_exists=True,
        toml_changed=False,
    )  # TODO: wire up
    assert result.status == "up_to_date"
    assert result.created == []
    assert result.skipped != []


@pytest.mark.instance_lifecycle_create
def test_create_instance_branch_changed_switches_worktree_if_clean():
    """Branch changed in toml, worktree is clean → switch in place."""
    result = create_instance(
        name="feat-789",
        workspace_root="/ws",
        instance_exists=True,
        repo_changes=[{"repo": "product-core", "old_branch": "feat-789-dev", "new_branch": "feat-999-dev", "dirty": False}],
    )  # TODO: wire up
    assert any(r["repo"] == "product-core" and r["action"] == "switched" for r in result.updated)


@pytest.mark.instance_lifecycle_create
def test_create_instance_branch_changed_dirty_worktree_surfaces_prompt():
    """Branch changed in toml, worktree is dirty → surfaces options (switch/stash/abort)."""
    result = create_instance(
        name="feat-789",
        workspace_root="/ws",
        instance_exists=True,
        repo_changes=[{"repo": "product-core", "old_branch": "feat-789-dev", "new_branch": "feat-999-dev", "dirty": True}],
    )  # TODO: wire up
    assert result.status == "needs_resolution"
    conflict = next(r for r in result.conflicts if r["repo"] == "product-core")
    assert conflict["options"] == ["switch", "stash", "abort"] or set(conflict["options"]) == {"switch", "stash", "abort"}


@pytest.mark.instance_lifecycle_create
def test_create_instance_new_repo_adds_worktree_only():
    """New repo added to toml → new worktree created; existing worktrees untouched."""
    result = create_instance(
        name="feat-789",
        workspace_root="/ws",
        instance_exists=True,
        new_repos=["scripts"],
    )  # TODO: wire up
    assert any(r == "scripts" for r in result.created)
    # existing worktrees must not appear in updated or re-created
    assert all(r != "product-core" for r in result.created)


@pytest.mark.instance_lifecycle_create
def test_create_instance_removed_repo_removes_worktree_keeps_branch():
    """Repo removed from toml → worktree removed; branch in bare repo untouched."""
    result = create_instance(
        name="feat-789",
        workspace_root="/ws",
        instance_exists=True,
        removed_repos=["customer-config"],
    )  # TODO: wire up
    assert any(r == "customer-config" for r in result.removed_worktrees)
    assert result.branches_deleted == []


# ---------------------------------------------------------------------------
# Workspace init
# ---------------------------------------------------------------------------

@pytest.mark.workspace_init
def test_init_fresh_workspace_runs_all_steps():
    result = init_workspace(
        workspace_root="/ws",
        workspace_toml_content="[repos]\nodoo = 'git@github.com:odoo/odoo.git'\n[clusters]\n\"19\" = {pg_version = \"16\", port = 5432}\n",
        docker_context=False,
        existing_repos=[],
    )  # TODO: wire up
    assert result.bare_clones_created != []
    assert result.db_clusters_provisioned != []
    assert result.proxy_block_written is True
    assert result.local_ca_installed is True


@pytest.mark.workspace_init
def test_init_skips_existing_repos():
    """init is idempotent: already-cloned repos skipped."""
    result = init_workspace(
        workspace_root="/ws",
        workspace_toml_content="[repos]\nodoo = 'git@github.com:odoo/odoo.git'\n[clusters]\n\"19\" = {pg_version = \"16\", port = 5432}\n",
        docker_context=False,
        existing_repos=["odoo"],
    )  # TODO: wire up
    assert "odoo" in result.skipped
    assert "odoo" not in result.bare_clones_created


@pytest.mark.workspace_init
def test_init_new_repo_added_clones_only_new():
    result = init_workspace(
        workspace_root="/ws",
        workspace_toml_content="[repos]\nodoo = 'git@github.com:odoo/odoo.git'\nproduct-core = 'git@bitbucket.org:org/pc.git'\n[clusters]\n\"19\" = {pg_version = \"16\", port = 5432}\n",
        docker_context=False,
        existing_repos=["odoo"],
    )  # TODO: wire up
    assert "product-core" in result.bare_clones_created
    assert "odoo" not in result.bare_clones_created


@pytest.mark.workspace_init
def test_init_docker_context_skips_system_level_steps():
    """In Docker: container owns system setup; owm skips CA cert, system proxy config."""
    result = init_workspace(
        workspace_root="/ws",
        workspace_toml_content="[repos]\nodoo = 'git@github.com:odoo/odoo.git'\n[clusters]\n\"19\" = {pg_version = \"16\", port = 5432}\n",
        docker_context=True,
        existing_repos=[],
    )  # TODO: wire up
    assert result.local_ca_installed is False
    assert result.bare_clones_created != []


@pytest.mark.workspace_init
def test_init_writes_reverse_proxy_block_for_dashboard():
    result = init_workspace(
        workspace_root="/ws",
        workspace_toml_content="[repos]\nodoo = 'git@github.com:odoo/odoo.git'\n[clusters]\n\"19\" = {pg_version = \"16\", port = 5432}\n",
        docker_context=False,
        existing_repos=[],
    )  # TODO: wire up
    assert result.proxy_block_written is True
    assert result.proxy_block_target == "owm_dashboard"


# === SPEC GAPS ===
# test_create_instance_dirty_worktree_stash_option: spec mentions stash as an option but
#   does not define the output or confirmation flow when user chooses stash.
# test_init_proxy_implementation: spec says "proxy implementation TBD (nginx vs caddy)";
#   proxy block format and target path cannot be fully tested until implementation chosen.
# test_create_instance_reads_toml_from_disk: spec does not state the exact path convention
#   for locating instance.toml (assumed instances/<name>/instance.toml).
