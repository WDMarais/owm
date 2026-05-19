"""
Smoke tests for owm init — real git subprocesses, no mocks.
Covers: Workspace init section.
"""
import os
import subprocess
import pytest
from unittest.mock import patch

from owm.workspace import init_workspace


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _make_remote(tmp_path, name):
    """Create a local bare repo that can serve as a git remote."""
    remote = tmp_path / "remotes" / f"{name}.git"
    remote.mkdir(parents=True)
    _git(["init", "--bare"], cwd=remote)
    # Seed with an initial commit so the repo isn't empty.
    src = tmp_path / "remotes" / f"{name}-seed"
    src.mkdir()
    _git(["init"], cwd=src)
    _git(["config", "user.email", "test@test.com"], cwd=src)
    _git(["config", "user.name", "Test"], cwd=src)
    (src / "README.md").write_text(f"# {name}\n")
    _git(["add", "."], cwd=src)
    _git(["commit", "-m", "init"], cwd=src)
    _git(["remote", "add", "origin", str(remote)], cwd=src)
    _git(["push", "origin", "HEAD:main"], cwd=src)
    return remote


def _workspace_toml(repo_urls: dict, pg_port: int = 5432) -> str:
    lines = ["[repos]"]
    for name, url in repo_urls.items():
        lines.append(f'{name} = "{url}"')
    lines += ['[clusters]', f'"19" = {{pg_version = "16", port = {pg_port}}}']
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Directory structure
# ---------------------------------------------------------------------------

@pytest.mark.smoke
def test_init_creates_expected_dirs(tmp_path):
    remote = _make_remote(tmp_path, "odoo")
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "workspace.toml").write_text(_workspace_toml({"odoo": str(remote)}))
    with patch("owm.workspace._superuser_exists", return_value=True):
        init_workspace(str(ws))
    for d in ["_repos", "_shared", "instances", "_archive", "_dumps"]:
        assert (ws / d).is_dir(), f"expected {d}/ to exist"


# ---------------------------------------------------------------------------
# Bare clone + fetch refspec
# ---------------------------------------------------------------------------

@pytest.mark.smoke
def test_init_clones_repo_as_bare(tmp_path):
    remote = _make_remote(tmp_path, "odoo")
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "workspace.toml").write_text(_workspace_toml({"odoo": str(remote)}))
    with patch("owm.workspace._superuser_exists", return_value=True):
        result = init_workspace(str(ws))
    assert "odoo" in result.bare_clones_created
    bare = ws / "_repos" / "odoo.git"
    assert bare.is_dir()
    # Verify it's a bare repo (has HEAD, not .git subdir).
    assert (bare / "HEAD").exists()
    assert not (bare / ".git").exists()


@pytest.mark.smoke
def test_init_configures_fetch_refspec(tmp_path):
    """Bare clone must have fetch refspec so `git fetch` updates branch refs."""
    remote = _make_remote(tmp_path, "odoo")
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "workspace.toml").write_text(_workspace_toml({"odoo": str(remote)}))
    with patch("owm.workspace._superuser_exists", return_value=True):
        init_workspace(str(ws))
    bare = ws / "_repos" / "odoo.git"
    r = subprocess.run(
        ["git", "config", "remote.origin.fetch"],
        cwd=str(bare), capture_output=True, text=True,
    )
    assert r.stdout.strip() == "+refs/heads/*:refs/heads/*"


@pytest.mark.smoke
def test_init_fetch_refspec_means_branches_visible_after_fetch(tmp_path):
    """After init + fetch, branch refs are resolvable in the bare clone."""
    remote = _make_remote(tmp_path, "odoo")
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "workspace.toml").write_text(_workspace_toml({"odoo": str(remote)}))
    with patch("owm.workspace._superuser_exists", return_value=True):
        init_workspace(str(ws))
    bare = ws / "_repos" / "odoo.git"
    r = subprocess.run(
        ["git", "rev-parse", "--verify", "refs/heads/main"],
        cwd=str(bare), capture_output=True, text=True,
    )
    assert r.returncode == 0, "main branch ref should be resolvable after init"


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

@pytest.mark.smoke
def test_init_idempotent_second_run_skips_existing(tmp_path):
    remote = _make_remote(tmp_path, "odoo")
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "workspace.toml").write_text(_workspace_toml({"odoo": str(remote)}))
    with patch("owm.workspace._superuser_exists", return_value=True):
        init_workspace(str(ws))
        result2 = init_workspace(str(ws))
    assert "odoo" in result2.skipped
    assert "odoo" not in result2.bare_clones_created


@pytest.mark.smoke
def test_init_second_repo_added_clones_only_new(tmp_path):
    remote_odoo = _make_remote(tmp_path, "odoo")
    remote_core = _make_remote(tmp_path, "product-core")
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "workspace.toml").write_text(_workspace_toml({"odoo": str(remote_odoo)}))
    with patch("owm.workspace._superuser_exists", return_value=True):
        init_workspace(str(ws))
    # Simulate adding a second repo to workspace.toml.
    (ws / "workspace.toml").write_text(_workspace_toml({
        "odoo": str(remote_odoo),
        "product-core": str(remote_core),
    }))
    with patch("owm.workspace._superuser_exists", return_value=True):
        result = init_workspace(str(ws))
    assert "product-core" in result.bare_clones_created
    assert "odoo" in result.skipped
