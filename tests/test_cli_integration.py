"""
CLI integration tests: invoke owm commands through Click's CliRunner.
Exercises the full command → library → disk path with no mocks.
All tests use tmp_workspace for isolation; no Postgres or git required.
"""
import pytest
from unittest.mock import patch
from click.testing import CliRunner

from owm.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


# ---------------------------------------------------------------------------
# owm new
# ---------------------------------------------------------------------------

@pytest.mark.cli_integration
def test_new_creates_instance_toml(runner, tmp_workspace):
    result = runner.invoke(cli, [
        "--workspace", str(tmp_workspace),
        "new", "feat-789", "odoo=main:shared",
    ])
    assert result.exit_code == 0
    toml = tmp_workspace / "instances" / "feat-789" / "instance.toml"
    assert toml.exists()


@pytest.mark.cli_integration
def test_new_prints_toml_path(runner, tmp_workspace):
    result = runner.invoke(cli, [
        "--workspace", str(tmp_workspace),
        "new", "feat-789", "odoo=main:shared",
    ])
    assert result.exit_code == 0
    assert "instance.toml" in result.output


@pytest.mark.cli_integration
def test_new_toml_contains_instance_name(runner, tmp_workspace):
    runner.invoke(cli, [
        "--workspace", str(tmp_workspace),
        "new", "feat-789", "odoo=main:shared",
    ])
    content = (tmp_workspace / "instances" / "feat-789" / "instance.toml").read_text()
    assert "feat-789" in content


@pytest.mark.cli_integration
def test_new_multiple_repos_written(runner, tmp_workspace):
    result = runner.invoke(cli, [
        "--workspace", str(tmp_workspace),
        "new", "feat-789",
        "odoo=main:shared",
        "product-core=feat-789-dev:main",
    ])
    assert result.exit_code == 0
    content = (tmp_workspace / "instances" / "feat-789" / "instance.toml").read_text()
    assert "odoo" in content
    assert "product-core" in content


@pytest.mark.cli_integration
def test_new_already_exists_exits_nonzero(runner, tmp_workspace):
    runner.invoke(cli, ["--workspace", str(tmp_workspace), "new", "feat-789", "odoo=main:shared"])
    result = runner.invoke(cli, ["--workspace", str(tmp_workspace), "new", "feat-789", "odoo=main:shared"])
    assert result.exit_code != 0


@pytest.mark.cli_integration
def test_new_already_exists_mentions_error_code(runner, tmp_workspace):
    runner.invoke(cli, ["--workspace", str(tmp_workspace), "new", "feat-789", "odoo=main:shared"])
    result = runner.invoke(cli, ["--workspace", str(tmp_workspace), "new", "feat-789", "odoo=main:shared"])
    assert "ALREADY_EXISTS" in result.output


@pytest.mark.cli_integration
def test_new_invalid_repo_spec_exits_nonzero(runner, tmp_workspace):
    result = runner.invoke(cli, [
        "--workspace", str(tmp_workspace),
        "new", "feat-789", "odoo",  # missing =
    ])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# owm new — workspace root inference from CWD
# ---------------------------------------------------------------------------

@pytest.mark.cli_integration
def test_new_cwd_inference_finds_workspace_toml(runner, tmp_workspace, monkeypatch):
    (tmp_workspace / "workspace.toml").write_text("[repos]\n[clusters]\n")
    monkeypatch.chdir(tmp_workspace)
    result = runner.invoke(cli, ["new", "feat-789", "odoo=main:shared"])
    assert result.exit_code == 0
    assert (tmp_workspace / "instances" / "feat-789" / "instance.toml").exists()


@pytest.mark.cli_integration
def test_new_cwd_inference_walks_up_to_parent(runner, tmp_workspace, monkeypatch):
    """workspace.toml in parent; CWD is a subdirectory."""
    (tmp_workspace / "workspace.toml").write_text("[repos]\n[clusters]\n")
    subdir = tmp_workspace / "some" / "subdir"
    subdir.mkdir(parents=True)
    monkeypatch.chdir(subdir)
    result = runner.invoke(cli, ["new", "feat-789", "odoo=main:shared"])
    assert result.exit_code == 0


@pytest.mark.cli_integration
def test_new_no_workspace_toml_exits_nonzero(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli, ["new", "feat-789", "odoo=main:shared"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# owm create
# ---------------------------------------------------------------------------

@pytest.mark.cli_integration
def test_create_exits_zero_on_success(runner, standard_instance_toml, tmp_workspace):
    with patch("owm.instance.create_worktree"), patch("owm.instance._create_instance_db"):
        result = runner.invoke(cli, [
            "--workspace", str(tmp_workspace),
            "create", "feat-789",
        ])
    assert result.exit_code == 0


@pytest.mark.cli_integration
def test_create_output_mentions_instance_url(runner, standard_instance_toml, tmp_workspace):
    with patch("owm.instance.create_worktree"), patch("owm.instance._create_instance_db"):
        result = runner.invoke(cli, [
            "--workspace", str(tmp_workspace),
            "create", "feat-789",
        ])
    assert "feat-789.localhost" in result.output


@pytest.mark.cli_integration
def test_create_writes_proxy_block_to_disk(runner, standard_instance_toml, tmp_workspace):
    with patch("owm.instance.create_worktree"), patch("owm.instance._create_instance_db"):
        runner.invoke(cli, [
            "--workspace", str(tmp_workspace),
            "create", "feat-789",
        ])
    assert (tmp_workspace / "_proxy" / "feat-789.conf").exists()


@pytest.mark.cli_integration
def test_create_writes_instance_conf_to_disk(runner, standard_instance_toml, tmp_workspace):
    with patch("owm.instance.create_worktree"), patch("owm.instance._create_instance_db"):
        runner.invoke(cli, [
            "--workspace", str(tmp_workspace),
            "create", "feat-789",
        ])
    assert (tmp_workspace / "instances" / "feat-789" / "instance.conf").exists()


# ---------------------------------------------------------------------------
# owm list
# ---------------------------------------------------------------------------

@pytest.mark.cli_integration
def test_list_empty_workspace_exits_zero(runner, tmp_workspace):
    result = runner.invoke(cli, ["--workspace", str(tmp_workspace), "list"])
    assert result.exit_code == 0


@pytest.mark.cli_integration
def test_list_empty_workspace_says_no_running(runner, tmp_workspace):
    result = runner.invoke(cli, ["--workspace", str(tmp_workspace), "list"])
    assert "no running instances" in result.output
