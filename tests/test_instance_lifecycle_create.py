"""
Tests for instance creation and workspace initialisation.
Covers: Instance lifecycle — create, Workspace init sections.
"""
import pytest
from unittest.mock import patch, MagicMock

from owm.instance import new_instance, create_instance
from owm.workspace import init_workspace


# ---------------------------------------------------------------------------
# owm new — generate instance.toml without materialising
# ---------------------------------------------------------------------------

@pytest.mark.instance_lifecycle_create
def test_new_instance_generates_toml_only(tmp_path):
    """owm new: writes instance.toml, no worktrees, no DB, no ports reserved."""
    result = new_instance(
        name="feat-789",
        repos={"odoo": "19.0:shared", "product-core": "feat-789-dev:dev", "customer-config": "feat-789-dev:dev"},
        workspace_root=str(tmp_path),
    )
    assert result.toml_path == str(tmp_path / "instances" / "feat-789" / "instance.toml")
    assert result.toml_content is not None
    assert result.materialised is False
    assert (tmp_path / "instances" / "feat-789" / "instance.toml").exists()


@pytest.mark.instance_lifecycle_create
def test_new_instance_toml_contains_autofilled_port(tmp_path):
    result = new_instance(
        name="feat-789",
        repos={"odoo": "19.0:shared", "product-core": "feat-789-dev:dev"},
        workspace_root=str(tmp_path),
    )
    assert "[server]" in result.toml_content
    assert "http_port" in result.toml_content


@pytest.mark.instance_lifecycle_create
def test_new_instance_toml_contains_autofilled_db_name(tmp_path):
    result = new_instance(
        name="feat-789",
        repos={"odoo": "19.0:shared"},
        workspace_root=str(tmp_path),
    )
    assert "[database]" in result.toml_content
    assert "feat-789" in result.toml_content


@pytest.mark.instance_lifecycle_create
def test_new_instance_already_exists_returns_error(tmp_path):
    inst_dir = tmp_path / "instances" / "feat-789"
    inst_dir.mkdir(parents=True)
    (inst_dir / "instance.toml").write_text("[repos]\n")
    with pytest.raises(Exception) as exc_info:
        new_instance(
            name="feat-789",
            repos={"odoo": "19.0:shared"},
            workspace_root=str(tmp_path),
        )
    assert "ALREADY_EXISTS" in str(exc_info.value)


# ---------------------------------------------------------------------------
# owm create — materialise from instance.toml
# ---------------------------------------------------------------------------

@pytest.mark.instance_lifecycle_create
def test_create_instance_materialises_all_resources(standard_instance_toml, tmp_workspace):
    """Fresh create: worktrees created, DB cloned, port reserved, nginx block written, odoo.conf generated."""
    with patch("owm.instance.create_worktree"), \
         patch("owm.instance._create_instance_db"):
        result = create_instance(
            name="feat-789",
            workspace_root=str(tmp_workspace),
            instance_exists=False,
        )
    assert result.worktrees_created is True
    assert result.db_created is True
    assert result.port_reserved is True
    assert result.proxy_block_written is True
    assert result.odoo_conf_generated is True


@pytest.mark.instance_lifecycle_create
def test_create_instance_writes_proxy_block_and_conf(standard_instance_toml, tmp_workspace):
    """create_instance writes _proxy/{name}.conf and instance.conf to disk."""
    with patch("owm.instance.create_worktree"), \
         patch("owm.instance._create_instance_db"):
        create_instance(
            name="feat-789",
            workspace_root=str(tmp_workspace),
            instance_exists=False,
        )
    assert (tmp_workspace / "_proxy" / "feat-789.conf").exists()
    proxy_content = (tmp_workspace / "_proxy" / "feat-789.conf").read_text()
    assert "feat_789" in proxy_content
    assert "8142" in proxy_content
    assert "feat-789.localhost" in proxy_content

    assert (tmp_workspace / "instances" / "feat-789" / "instance.conf").exists()
    conf_content = (tmp_workspace / "instances" / "feat-789" / "instance.conf").read_text()
    assert "http_port = 8142" in conf_content
    assert "db_name = owm_test_feat789" in conf_content


@pytest.mark.instance_lifecycle_create
def test_create_instance_port_conflict_reassigns(standard_instance_toml, tmp_workspace):
    """If another instance holds port 8142, create_instance picks a fresh one."""
    # Plant a second instance that already occupies port 8142
    other_dir = tmp_workspace / "instances" / "other-999"
    other_dir.mkdir()
    (other_dir / "instance.toml").write_text(
        "[repos]\n\n[database]\nname = \"owm_other\"\npg_port = 5432\n"
        "[server]\nhttp_port = 8142\ngevent_port = 8143\nworkers = 2\n"
    )
    with patch("owm.instance.create_worktree"), \
         patch("owm.instance._create_instance_db"):
        create_instance(
            name="feat-789",
            workspace_root=str(tmp_workspace),
            instance_exists=False,
        )
    conf_content = (tmp_workspace / "instances" / "feat-789" / "instance.conf").read_text()
    # port must not be 8142 since that's taken
    assert "http_port = 8142" not in conf_content


@pytest.mark.instance_lifecycle_create
def test_create_instance_idempotent_when_unchanged():
    """Instance already exists and toml unchanged → all steps skipped."""
    result = create_instance(
        name="feat-789",
        workspace_root="/ws",
        instance_exists=True,
        toml_changed=False,
    )
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
    )
    assert any(r["repo"] == "product-core" and r["action"] == "switched" for r in result.updated)


@pytest.mark.instance_lifecycle_create
def test_create_instance_branch_changed_dirty_worktree_surfaces_prompt():
    """Branch changed in toml, worktree is dirty → surfaces options (switch/stash/abort)."""
    result = create_instance(
        name="feat-789",
        workspace_root="/ws",
        instance_exists=True,
        repo_changes=[{"repo": "product-core", "old_branch": "feat-789-dev", "new_branch": "feat-999-dev", "dirty": True}],
    )
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
    )
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
    )
    assert any(r == "customer-config" for r in result.removed_worktrees)
    assert result.branches_deleted == []


# ---------------------------------------------------------------------------
# Workspace init
# ---------------------------------------------------------------------------

_SIMPLE_WS_TOML = (
    '[repos]\nodoo = "git@github.com:odoo/odoo.git"\n'
    '[clusters]\n"19" = {pg_version = "16", port = 5432}\n'
)
_TWO_REPO_WS_TOML = (
    '[repos]\nodoo = "git@github.com:odoo/odoo.git"\nproduct-core = "git@bitbucket.org:org/pc.git"\n'
    '[clusters]\n"19" = {pg_version = "16", port = 5432}\n'
)


@pytest.mark.workspace_init
def test_init_fresh_workspace_runs_all_steps(tmp_path):
    (tmp_path / "workspace.toml").write_text(_SIMPLE_WS_TOML)
    with patch("owm.workspace._superuser_exists", return_value=True), \
         patch("owm.workspace._git_clone_bare"):
        result = init_workspace(str(tmp_path), docker_context=False)
    assert result.bare_clones_created != []
    assert result.db_clusters_provisioned != []
    assert result.proxy_block_written is True
    assert result.local_ca_installed is True


@pytest.mark.workspace_init
def test_init_skips_existing_repos(tmp_path):
    """init is idempotent: already-cloned repos skipped."""
    (tmp_path / "workspace.toml").write_text(_SIMPLE_WS_TOML)
    (tmp_path / "_repos" / "odoo.git").mkdir(parents=True)
    with patch("owm.workspace._superuser_exists", return_value=True), \
         patch("owm.workspace._git_clone_bare"):
        result = init_workspace(str(tmp_path))
    assert "odoo" in result.skipped
    assert "odoo" not in result.bare_clones_created


@pytest.mark.workspace_init
def test_init_new_repo_added_clones_only_new(tmp_path):
    (tmp_path / "workspace.toml").write_text(_TWO_REPO_WS_TOML)
    (tmp_path / "_repos" / "odoo.git").mkdir(parents=True)
    with patch("owm.workspace._superuser_exists", return_value=True), \
         patch("owm.workspace._git_clone_bare"):
        result = init_workspace(str(tmp_path))
    assert "product-core" in result.bare_clones_created
    assert "odoo" not in result.bare_clones_created


@pytest.mark.workspace_init
def test_init_docker_context_skips_system_level_steps(tmp_path):
    """In Docker: container owns system setup; owm skips CA cert, system proxy config."""
    (tmp_path / "workspace.toml").write_text(_SIMPLE_WS_TOML)
    with patch("owm.workspace._superuser_exists", return_value=True), \
         patch("owm.workspace._git_clone_bare"):
        result = init_workspace(str(tmp_path), docker_context=True)
    assert result.local_ca_installed is False
    assert result.bare_clones_created != []


@pytest.mark.workspace_init
def test_init_writes_reverse_proxy_block_for_dashboard(tmp_path):
    (tmp_path / "workspace.toml").write_text(_SIMPLE_WS_TOML)
    with patch("owm.workspace._superuser_exists", return_value=True), \
         patch("owm.workspace._git_clone_bare"):
        result = init_workspace(str(tmp_path), docker_context=False)
    assert result.proxy_block_written is True
    assert result.proxy_block_target == "owm_dashboard"


# === SPEC GAPS ===
# test_create_instance_dirty_worktree_stash_option: spec mentions stash as an option but
#   does not define the output or confirmation flow when user chooses stash.
# test_init_proxy_implementation: spec says "proxy implementation TBD (nginx vs caddy)";
#   proxy block format and target path cannot be fully tested until implementation chosen.
# test_create_instance_reads_toml_from_disk: spec does not state the exact path convention
#   for locating instance.toml (assumed instances/<name>/instance.toml).
