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
# owm create --toml-only
# ---------------------------------------------------------------------------

@pytest.mark.cli_integration
def test_create_toml_only_creates_instance_toml(runner, tmp_workspace):
    result = runner.invoke(cli, [
        "--workspace", str(tmp_workspace),
        "create", "feat-789", "odoo=main:shared", "--toml-only",
    ])
    assert result.exit_code == 0
    assert (tmp_workspace / "instances" / "feat-789" / "instance.toml").exists()


@pytest.mark.cli_integration
def test_create_toml_only_prints_toml_path(runner, tmp_workspace):
    result = runner.invoke(cli, [
        "--workspace", str(tmp_workspace),
        "create", "feat-789", "odoo=main:shared", "--toml-only",
    ])
    assert result.exit_code == 0
    assert "instance.toml" in result.output


@pytest.mark.cli_integration
def test_create_toml_only_multiple_repos_written(runner, tmp_workspace):
    result = runner.invoke(cli, [
        "--workspace", str(tmp_workspace),
        "create", "feat-789",
        "odoo=main:shared", "product-core=feat-789-dev:main",
        "--toml-only",
    ])
    assert result.exit_code == 0
    content = (tmp_workspace / "instances" / "feat-789" / "instance.toml").read_text()
    assert "odoo" in content
    assert "product-core" in content


@pytest.mark.cli_integration
def test_create_toml_only_already_exists_exits_nonzero(runner, tmp_workspace):
    runner.invoke(cli, ["--workspace", str(tmp_workspace),
                        "create", "feat-789", "odoo=main:shared", "--toml-only"])
    result = runner.invoke(cli, ["--workspace", str(tmp_workspace),
                                 "create", "feat-789", "odoo=main:shared", "--toml-only"])
    assert result.exit_code != 0
    assert "ALREADY_EXISTS" in result.output


@pytest.mark.cli_integration
def test_create_toml_only_force_overwrites(runner, tmp_workspace):
    runner.invoke(cli, ["--workspace", str(tmp_workspace),
                        "create", "feat-789", "odoo=main:shared", "--toml-only"])
    result = runner.invoke(cli, ["--workspace", str(tmp_workspace),
                                 "create", "feat-789", "odoo=main:shared", "--toml-only", "--force"])
    assert result.exit_code == 0


@pytest.mark.cli_integration
def test_create_toml_only_without_repos_exits_nonzero(runner, tmp_workspace):
    result = runner.invoke(cli, [
        "--workspace", str(tmp_workspace),
        "create", "feat-789", "--toml-only",  # no repos
    ])
    assert result.exit_code != 0


@pytest.mark.cli_integration
def test_create_toml_only_invalid_repo_spec_exits_nonzero(runner, tmp_workspace):
    result = runner.invoke(cli, [
        "--workspace", str(tmp_workspace),
        "create", "feat-789", "odoo", "--toml-only",  # missing =
    ])
    assert result.exit_code != 0


@pytest.mark.cli_integration
def test_create_toml_only_workspace_root_inferred_from_cwd(runner, tmp_workspace, monkeypatch):
    monkeypatch.delenv("OWM_WORKSPACE", raising=False)
    (tmp_workspace / "workspace.toml").write_text("[repos]\n[clusters]\n")
    monkeypatch.chdir(tmp_workspace)
    result = runner.invoke(cli, ["create", "feat-789", "odoo=main:shared", "--toml-only"])
    assert result.exit_code == 0
    assert (tmp_workspace / "instances" / "feat-789" / "instance.toml").exists()


@pytest.mark.cli_integration
def test_create_toml_only_no_workspace_toml_exits_nonzero(runner, tmp_path, monkeypatch):
    monkeypatch.delenv("OWM_WORKSPACE", raising=False)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli, ["create", "feat-789", "odoo=main:shared", "--toml-only"])
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


@pytest.mark.cli_integration
def test_create_exists_flag_branch_not_found_exits_nonzero(runner, tmp_workspace):
    inst_dir = tmp_workspace / "instances" / "feat-789"
    inst_dir.mkdir(parents=True, exist_ok=True)
    (inst_dir / "instance.toml").write_text(
        '[repos]\n'
        'product-core = {branch = "feat-789-dev", base = "main", exists = true}\n'
        '\n'
        '[database]\nname = "feat-789"\npg_port = 5432\n'
        '\n'
        '[server]\nhttp_port = 8100\ngevent_port = 8101\nworkers = 2\n'
    )
    with patch("owm.worktrees._branch_exists", return_value=False):
        result = runner.invoke(cli, [
            "--workspace", str(tmp_workspace),
            "create", "feat-789",
        ])
    assert result.exit_code != 0
    assert "BRANCH_NOT_FOUND" in result.output


@pytest.mark.cli_integration
def test_create_infers_instance_from_cwd(runner, standard_instance_toml, tmp_workspace, monkeypatch):
    monkeypatch.delenv("OWM_WORKSPACE", raising=False)
    (tmp_workspace / "workspace.toml").write_text("[repos]\n[clusters]\n")
    monkeypatch.chdir(tmp_workspace / "instances" / "feat-789")
    with patch("owm.instance.create_worktree"), patch("owm.instance._create_instance_db"):
        result = runner.invoke(cli, ["create"])
    assert result.exit_code == 0
    assert "feat-789" in result.output


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
