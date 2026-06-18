"""
CLI integration tests: invoke owm commands through Click's CliRunner.
Exercises the full command → library → disk path with no mocks.
All tests use tmp_workspace for isolation; no Postgres or git required.
"""
import subprocess
import tomllib
from pathlib import Path

import pytest
from unittest.mock import patch, MagicMock
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
    with patch("owm.instance.create_worktree"), patch("owm.instance.create_db", return_value=MagicMock(full_install_required=True)):
        result = runner.invoke(cli, [
            "--workspace", str(tmp_workspace),
            "create", "feat-789",
        ])
    assert result.exit_code == 0


@pytest.mark.cli_integration
def test_create_output_mentions_instance_url(runner, standard_instance_toml, tmp_workspace):
    with patch("owm.instance.create_worktree"), patch("owm.instance.create_db", return_value=MagicMock(full_install_required=True)):
        result = runner.invoke(cli, [
            "--workspace", str(tmp_workspace),
            "create", "feat-789",
        ])
    assert "feat-789.localhost" in result.output


@pytest.mark.cli_integration
def test_create_writes_proxy_block_to_disk(runner, standard_instance_toml, tmp_workspace):
    with patch("owm.instance.create_worktree"), patch("owm.instance.create_db", return_value=MagicMock(full_install_required=True)):
        runner.invoke(cli, [
            "--workspace", str(tmp_workspace),
            "create", "feat-789",
        ])
    assert (tmp_workspace / "_proxy" / "feat-789.conf").exists()


@pytest.mark.cli_integration
def test_create_writes_instance_conf_to_disk(runner, standard_instance_toml, tmp_workspace):
    with patch("owm.instance.create_worktree"), patch("owm.instance.create_db", return_value=MagicMock(full_install_required=True)):
        runner.invoke(cli, [
            "--workspace", str(tmp_workspace),
            "create", "feat-789",
        ])
    assert (tmp_workspace / "instances" / "feat-789" / "instance.conf").exists()


@pytest.mark.cli_integration
def test_create_exists_flag_branch_not_found_exits_nonzero(runner, tmp_workspace, make_upstream_repo):
    # Real bare repo for product-core seeded with only 'main' — the requested
    # feat-789-dev branch exists neither locally nor on origin, so +exists fails.
    upstream = make_upstream_repo("product-core")
    subprocess.run(
        ["git", "clone", "--bare", str(upstream),
         str(tmp_workspace / "_repos" / "product-core.git")],
        check=True, capture_output=True,
    )
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
    result = runner.invoke(cli, [
        "--workspace", str(tmp_workspace),
        "create", "feat-789",
    ])
    assert result.exit_code != 0
    assert "BRANCH_NOT_FOUND" in result.output


@pytest.mark.cli_integration
def test_create_infers_instance_from_cwd(runner, standard_instance_toml, tmp_workspace, monkeypatch):
    monkeypatch.delenv("OWM_WORKSPACE", raising=False)
    # Minimal proxy-less workspace, but with one has_addons repo the instance uses:
    # create refuses an instance whose addons_path resolves to empty.
    (tmp_workspace / "workspace.toml").write_text(
        "[repos]\n"
        'odoo_like = {path = "/dev/null", has_addons = true}\n'
        "[clusters]\n"
    )
    monkeypatch.chdir(tmp_workspace / "instances" / "feat-789")
    with patch("owm.instance.create_worktree"), patch("owm.instance.create_db", return_value=MagicMock(full_install_required=True)):
        result = runner.invoke(cli, ["create"])
    assert result.exit_code == 0
    assert "feat-789" in result.output


# ---------------------------------------------------------------------------
# owm delete
# ---------------------------------------------------------------------------

@pytest.mark.cli_integration
def test_delete_running_instance_exits_nonzero(runner, standard_instance_toml, tmp_workspace):
    with patch("owm.cli._is_running", return_value=True):
        result = runner.invoke(cli, [
            "--workspace", str(tmp_workspace),
            "delete", "feat-789",
        ])
    assert result.exit_code != 0
    assert "INSTANCE_RUNNING" in result.output or "stop" in result.output.lower()


@pytest.mark.cli_integration
def test_delete_no_force_shows_checklist_exits_nonzero(runner, standard_instance_toml, tmp_workspace):
    with patch("owm.cli._is_running", return_value=False):
        result = runner.invoke(cli, [
            "--workspace", str(tmp_workspace),
            "delete", "feat-789",
        ])
    assert result.exit_code != 0
    assert "force" in result.output.lower()


@pytest.mark.cli_integration
def test_delete_force_exits_zero(runner, standard_instance_toml, tmp_workspace):
    with patch("owm.cli._is_running", return_value=False), \
         patch("owm.operations._remove_worktrees"), \
         patch("owm.operations._dropdb_archive"), \
         patch("owm.operations._remove_proxy_block"), \
         patch("owm.operations.shutil.rmtree"):
        result = runner.invoke(cli, [
            "--workspace", str(tmp_workspace),
            "delete", "feat-789", "--force",
        ])
    assert result.exit_code == 0
    assert "deleted" in result.output


# ---------------------------------------------------------------------------
# owm rename
# ---------------------------------------------------------------------------

@pytest.mark.cli_integration
def test_rename_running_instance_exits_nonzero(runner, tmp_workspace):
    with patch("owm.cli._is_running", return_value=True):
        result = runner.invoke(cli, [
            "--workspace", str(tmp_workspace),
            "rename", "feat-789", "pd-789",
        ])
    assert result.exit_code != 0
    assert "INSTANCE_RUNNING" in result.output or "stop" in result.output.lower()


@pytest.mark.cli_integration
def test_rename_from_inside_instance_exits_nonzero(runner, tmp_workspace, monkeypatch):
    monkeypatch.delenv("OWM_WORKSPACE", raising=False)
    (tmp_workspace / "instances" / "feat-789").mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_workspace / "instances" / "feat-789")
    with patch("owm.cli._is_running", return_value=False):
        result = runner.invoke(cli, [
            "--workspace", str(tmp_workspace),
            "rename", "feat-789", "pd-789",
        ])
    assert result.exit_code != 0
    assert "inside" in result.output.lower() or "workspace root" in result.output.lower()


@pytest.mark.cli_integration
def test_rename_stopped_exits_zero_with_output(runner, standard_instance_toml, tmp_workspace):
    with patch("owm.cli._is_running", return_value=False), \
         patch("owm.operations.subprocess.run") as mock_run, \
         patch("owm.operations.shutil.move"):
        mock_run.return_value.returncode = 0
        result = runner.invoke(cli, [
            "--workspace", str(tmp_workspace),
            "rename", "feat-789", "pd-789",
        ])
    assert result.exit_code == 0
    assert "feat-789" in result.output
    assert "pd-789" in result.output


# ---------------------------------------------------------------------------
# owm logs
# ---------------------------------------------------------------------------

@pytest.mark.cli_integration
def test_logs_prints_lines(runner, tmp_workspace):
    import json
    inst_dir = tmp_workspace / "instances" / "feat-789"
    inst_dir.mkdir(parents=True, exist_ok=True)
    lines = [{"level": "INFO", "msg": "started"}, {"level": "ERROR", "msg": "crash"}]
    (inst_dir / "instance.log").write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    result = runner.invoke(cli, ["--workspace", str(tmp_workspace), "logs", "feat-789"])
    assert result.exit_code == 0
    assert "started" in result.output
    assert "crash" in result.output


@pytest.mark.cli_integration
def test_logs_level_filter(runner, tmp_workspace):
    import json
    inst_dir = tmp_workspace / "instances" / "feat-789"
    inst_dir.mkdir(parents=True, exist_ok=True)
    lines = [{"level": "INFO", "msg": "started"}, {"level": "ERROR", "msg": "crash"}]
    (inst_dir / "instance.log").write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    result = runner.invoke(cli, [
        "--workspace", str(tmp_workspace), "logs", "feat-789", "--level", "ERROR",
    ])
    assert result.exit_code == 0
    assert "crash" in result.output
    assert "started" not in result.output


@pytest.mark.cli_integration
def test_logs_follow_not_implemented(runner, tmp_workspace):
    result = runner.invoke(cli, ["--workspace", str(tmp_workspace), "logs", "feat-789", "--follow"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# owm db-dump / db-restore
# ---------------------------------------------------------------------------

@pytest.mark.cli_integration
def test_db_dump_exits_zero_and_prints_path(runner, standard_instance_toml, tmp_workspace):
    with patch("owm.operations._pg_dump"), patch("owm.operations.os.makedirs"):
        result = runner.invoke(cli, ["--workspace", str(tmp_workspace), "db-dump", "feat-789"])
    assert result.exit_code == 0
    assert "dump:" in result.output
    assert "feat-789" in result.output


@pytest.mark.cli_integration
def test_db_dump_explicit_out_path(runner, standard_instance_toml, tmp_workspace, tmp_path):
    out = str(tmp_path / "snap.dump")
    with patch("owm.operations._pg_dump"), patch("owm.operations.os.makedirs"):
        result = runner.invoke(cli, [
            "--workspace", str(tmp_workspace), "db-dump", "feat-789", "--out", out,
        ])
    assert result.exit_code == 0
    assert out in result.output


@pytest.mark.cli_integration
def test_db_restore_exits_zero_and_prints_path(runner, standard_instance_toml, tmp_workspace):
    with patch("owm.cli._is_running", return_value=False), \
         patch("owm.operations._pg_restore"):
        result = runner.invoke(cli, [
            "--workspace", str(tmp_workspace), "db-restore", "feat-789", "snap.dump",
        ])
    assert result.exit_code == 0
    assert "restored:" in result.output


@pytest.mark.cli_integration
def test_db_restore_running_exits_nonzero(runner, standard_instance_toml, tmp_workspace):
    with patch("owm.cli._is_running", return_value=True):
        result = runner.invoke(cli, [
            "--workspace", str(tmp_workspace), "db-restore", "feat-789", "snap.dump",
        ])
    assert result.exit_code != 0
    assert "INSTANCE_RUNNING" in result.output or "stop" in result.output.lower()


# ---------------------------------------------------------------------------
# owm validate
# ---------------------------------------------------------------------------

@pytest.mark.cli_integration
def test_validate_valid_toml_exits_zero(runner, standard_instance_toml, tmp_workspace):
    # Valid toml + no config errors = exit 0 (materialised-state warnings are expected in test env)
    result = runner.invoke(cli, ["--workspace", str(tmp_workspace), "validate", "feat-789"])
    assert result.exit_code == 0
    assert "error:" not in result.output


@pytest.mark.cli_integration
def test_validate_missing_toml_exits_nonzero(runner, tmp_workspace):
    result = runner.invoke(cli, ["--workspace", str(tmp_workspace), "validate", "feat-789"])
    assert result.exit_code != 0


@pytest.mark.cli_integration
def test_validate_live_flag_noted_in_output(runner, standard_instance_toml, tmp_workspace):
    # --live may produce warnings in test env (no real DB/HTTP) but must not error on the flag itself
    result = runner.invoke(cli, ["--workspace", str(tmp_workspace), "validate", "feat-789", "--live"])
    assert result.exit_code == 0
    assert "live" in result.output


# ---------------------------------------------------------------------------
# owm kill
# ---------------------------------------------------------------------------

@pytest.mark.cli_integration
def test_kill_not_running_exits_zero(runner, tmp_workspace):
    with patch("owm.instance._read_pid", return_value=None):
        result = runner.invoke(cli, ["--workspace", str(tmp_workspace), "kill", "feat-789"])
    assert result.exit_code == 0
    assert "not running" in result.output


@pytest.mark.cli_integration
def test_kill_running_exits_zero_with_pid(runner, tmp_workspace):
    with patch("owm.instance._read_pid", return_value=1234), \
         patch("owm.instance._process_alive", return_value=True), \
         patch("owm.instance.os.kill"), \
         patch("owm.instance._clear_pid"), \
         patch("owm.instance.instance_separator"), \
         patch("owm.instance.workspace_log"):
        result = runner.invoke(cli, ["--workspace", str(tmp_workspace), "kill", "feat-789"])
    assert result.exit_code == 0
    assert "killed" in result.output
    assert "1234" in result.output


# ---------------------------------------------------------------------------
# owm health
# ---------------------------------------------------------------------------

@pytest.mark.cli_integration
def test_health_stopped_instance(runner, standard_instance_toml, tmp_workspace):
    with patch("owm.instance._read_pid", return_value=None):
        result = runner.invoke(cli, ["--workspace", str(tmp_workspace), "health", "feat-789"])
    assert result.exit_code == 0
    assert "stopped" in result.output


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


# ---------------------------------------------------------------------------
# owm env
# ---------------------------------------------------------------------------

@pytest.mark.cli_integration
def test_env_exits_zero_and_prints_key(runner, standard_instance_toml, tmp_workspace):
    result = runner.invoke(cli, ["--workspace", str(tmp_workspace), "env", "feat-789"])
    assert result.exit_code == 0
    assert "DB_NAME" in result.output


@pytest.mark.cli_integration
def test_env_dotenv_format(runner, standard_instance_toml, tmp_workspace):
    result = runner.invoke(cli, [
        "--workspace", str(tmp_workspace), "env", "feat-789", "--format", "dotenv",
    ])
    assert result.exit_code == 0
    assert "DB_NAME=" in result.output


@pytest.mark.cli_integration
def test_env_json_format(runner, standard_instance_toml, tmp_workspace):
    import json
    result = runner.invoke(cli, [
        "--workspace", str(tmp_workspace), "env", "feat-789", "--format", "json",
    ])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert "DB_NAME" in parsed


@pytest.mark.cli_integration
def test_env_shell_format(runner, standard_instance_toml, tmp_workspace):
    result = runner.invoke(cli, [
        "--workspace", str(tmp_workspace), "env", "feat-789", "--format", "shell",
    ])
    assert result.exit_code == 0
    assert "export DB_NAME=" in result.output


# ---------------------------------------------------------------------------
# owm archive
# ---------------------------------------------------------------------------

@pytest.mark.cli_integration
def test_archive_running_exits_nonzero(runner, standard_instance_toml, tmp_workspace):
    with patch("owm.cli._is_running", return_value=True):
        result = runner.invoke(cli, [
            "--workspace", str(tmp_workspace), "archive", "feat-789",
        ])
    assert result.exit_code != 0
    assert "INSTANCE_RUNNING" in result.output


@pytest.mark.cli_integration
def test_archive_stopped_exits_zero(runner, standard_instance_toml, tmp_workspace):
    with patch("owm.cli._is_running", return_value=False), \
         patch("owm.archive._remove_worktrees"), \
         patch("owm.archive._dropdb_archive"), \
         patch("owm.archive._pg_dump_archive"):
        result = runner.invoke(cli, [
            "--workspace", str(tmp_workspace), "archive", "feat-789",
        ])
    assert result.exit_code == 0
    assert "archived" in result.output


@pytest.mark.cli_integration
def test_archive_output_mentions_instance_name(runner, standard_instance_toml, tmp_workspace):
    with patch("owm.cli._is_running", return_value=False), \
         patch("owm.archive._remove_worktrees"), \
         patch("owm.archive._dropdb_archive"), \
         patch("owm.archive._pg_dump_archive"):
        result = runner.invoke(cli, [
            "--workspace", str(tmp_workspace), "archive", "feat-789",
        ])
    assert "feat-789" in result.output


# ---------------------------------------------------------------------------
# owm install
# ---------------------------------------------------------------------------

@pytest.mark.cli_integration
def test_install_saves_new_module_to_toml(runner, standard_instance_toml, tmp_workspace):
    # Guards the cmd_install save path: a freshly-installed module must be appended
    # to [install].modules in the on-disk instance.toml. The odoo spawn is mocked
    # (not under test); the toml-path derivation + append run for real — so this
    # would catch a regression of the `toml_path` NameError the path had.
    with patch("owm.cli._is_running", return_value=False), \
         patch("owm.cli._query_installed_modules", return_value=[]), \
         patch("owm.cli.start_instance"), \
         patch("owm.cli.stop_instance"):
        result = runner.invoke(cli, [
            "--workspace", str(tmp_workspace), "install", "feat-789", "test_brand_new",
        ])
    assert result.exit_code == 0, result.output
    saved = tomllib.loads(standard_instance_toml.read_text())
    assert "test_brand_new" in saved["install"]["modules"]


# ---------------------------------------------------------------------------
# owm upgrade
# ---------------------------------------------------------------------------

@pytest.mark.cli_integration
def test_upgrade_all_modules_exits_zero(runner, tmp_workspace):
    result = runner.invoke(cli, [
        "--workspace", str(tmp_workspace), "upgrade", "feat-789",
    ])
    assert result.exit_code == 0
    assert "upgraded" in result.output


@pytest.mark.cli_integration
def test_upgrade_specific_modules_exits_zero(runner, tmp_workspace):
    result = runner.invoke(cli, [
        "--workspace", str(tmp_workspace), "upgrade", "feat-789", "sale", "account",
    ])
    assert result.exit_code == 0
    assert "sale" in result.output
    assert "account" in result.output


@pytest.mark.cli_integration
def test_upgrade_reinstall_flag(runner, tmp_workspace):
    result = runner.invoke(cli, [
        "--workspace", str(tmp_workspace), "upgrade", "feat-789", "--reinstall",
    ])
    assert result.exit_code == 0
    assert "reinstalled" in result.output


# ---------------------------------------------------------------------------
# owm fetch
# ---------------------------------------------------------------------------

@pytest.mark.cli_integration
def test_fetch_no_repos_exits_zero(runner, tmp_workspace):
    # override workspace.toml to have no repos
    (tmp_workspace / "workspace.toml").write_text("[repos]\n\n[clusters]\n\n[proxy]\nbackend=\"nginx\"\ndomain_suffix=\"localhost\"\n")
    result = runner.invoke(cli, ["--workspace", str(tmp_workspace), "fetch"])
    assert result.exit_code == 0
    assert "no repos configured" in result.output


@pytest.mark.cli_integration
def test_fetch_repo_with_update_printed(runner, tmp_workspace):
    (tmp_workspace / "workspace.toml").write_text('[repos]\nodoo = "git@example.com:odoo.git"\n[clusters]\n')
    (tmp_workspace / "_repos" / "odoo.git").mkdir(parents=True, exist_ok=True)
    with patch("owm.sync.git_fetch_bare", return_value=True):
        result = runner.invoke(cli, ["--workspace", str(tmp_workspace), "fetch"])
    assert result.exit_code == 0
    assert "odoo" in result.output
    assert "updated" in result.output


@pytest.mark.cli_integration
def test_fetch_repo_timeout_prints_warning(runner, tmp_workspace):
    (tmp_workspace / "workspace.toml").write_text('[repos]\nodoo = "git@example.com:odoo.git"\n[clusters]\n')
    (tmp_workspace / "_repos" / "odoo.git").mkdir(parents=True, exist_ok=True)
    from owm.errors import OwmError, FETCH_TIMEOUT
    with patch("owm.sync.git_fetch_bare", side_effect=OwmError("fetch timed out after 30s", code=FETCH_TIMEOUT)):
        result = runner.invoke(cli, ["--workspace", str(tmp_workspace), "fetch"])
    assert result.exit_code == 0
    assert "warning" in result.output
    assert "FETCH_TIMEOUT" in result.output


@pytest.mark.cli_integration
def test_fetch_repo_no_update_says_up_to_date(runner, tmp_workspace):
    (tmp_workspace / "workspace.toml").write_text('[repos]\nodoo = "git@example.com:odoo.git"\n[clusters]\n')
    (tmp_workspace / "_repos" / "odoo.git").mkdir(parents=True, exist_ok=True)
    with patch("owm.sync.git_fetch_bare", return_value=False):
        result = runner.invoke(cli, ["--workspace", str(tmp_workspace), "fetch"])
    assert result.exit_code == 0
    assert "up to date" in result.output


# ---------------------------------------------------------------------------
# owm sync
# ---------------------------------------------------------------------------

@pytest.mark.cli_integration
def test_sync_clean_repo_skipped(runner, standard_instance_toml, tmp_workspace, make_instance_worktrees):
    make_instance_worktrees(tmp_workspace, "feat-789")
    with patch("owm.cli.read_repo_state", return_value={"status": "clean"}), \
         patch("owm.cli.git_fast_forward"):
        result = runner.invoke(cli, [
            "--workspace", str(tmp_workspace), "sync", "feat-789",
        ])
    assert result.exit_code == 0
    assert "skipped" in result.output


@pytest.mark.cli_integration
def test_sync_behind_repo_fast_forwarded(runner, standard_instance_toml, tmp_workspace, make_instance_worktrees):
    make_instance_worktrees(tmp_workspace, "feat-789")
    with patch("owm.cli.read_repo_state", return_value={"status": "behind", "behind_by": 2}), \
         patch("owm.cli.git_fast_forward") as mock_ff:
        result = runner.invoke(cli, [
            "--workspace", str(tmp_workspace), "sync", "feat-789",
        ])
    assert result.exit_code == 0
    assert "fast-forwarded" in result.output
    assert mock_ff.called


@pytest.mark.cli_integration
def test_sync_rebase_flag_rebases_diverged(runner, standard_instance_toml, tmp_workspace, make_instance_worktrees):
    make_instance_worktrees(tmp_workspace, "feat-789")
    with patch("owm.cli.read_repo_state", return_value={"status": "diverged", "ahead_by": 1, "behind_by": 1}), \
         patch("owm.cli.git_rebase") as mock_rb:
        result = runner.invoke(cli, [
            "--workspace", str(tmp_workspace), "sync", "feat-789", "--rebase",
        ])
    assert result.exit_code == 0
    assert "rebased" in result.output
    assert mock_rb.called


# ---------------------------------------------------------------------------
# owm push
# ---------------------------------------------------------------------------

@pytest.mark.cli_integration
def test_push_all_exits_zero(runner, standard_instance_toml, tmp_workspace, make_instance_worktrees):
    make_instance_worktrees(tmp_workspace, "feat-789")
    with patch("owm.cli.read_repo_state", return_value={"status": "ahead", "ahead_by": 1}), \
         patch("owm.cli.git_push"):
        result = runner.invoke(cli, [
            "--workspace", str(tmp_workspace), "push", "feat-789", "--all",
        ])
    assert result.exit_code == 0
    assert "pushed" in result.output


@pytest.mark.cli_integration
def test_push_shared_repo_skipped(runner, tmp_workspace, make_instance_worktrees):
    inst_dir = tmp_workspace / "instances" / "feat-789"
    inst_dir.mkdir(parents=True, exist_ok=True)
    (inst_dir / "instance.toml").write_text(
        '[repos]\nodoo = {branch = "main", shared = true}\n\n'
        '[database]\nname = "feat-789"\npg_port = 5432\n\n'
        '[server]\nhttp_port = 8100\ngevent_port = 8101\nworkers = 2\n'
    )
    make_instance_worktrees(tmp_workspace, "feat-789")
    with patch("owm.cli.read_repo_state", return_value={"status": "ahead"}), \
         patch("owm.cli.git_push"):
        result = runner.invoke(cli, [
            "--workspace", str(tmp_workspace), "push", "feat-789", "--all",
        ])
    assert result.exit_code == 0
    assert "skipped" in result.output


# ---------------------------------------------------------------------------
# owm reset
# ---------------------------------------------------------------------------

@pytest.mark.cli_integration
def test_reset_all_clean_exits_zero(runner, standard_instance_toml, tmp_workspace, make_instance_worktrees):
    make_instance_worktrees(tmp_workspace, "feat-789")
    with patch("owm.cli.read_repo_state", return_value={"status": "clean"}), \
         patch("owm.cli.git_reset_hard"):
        result = runner.invoke(cli, [
            "--workspace", str(tmp_workspace), "reset", "feat-789", "--all",
        ])
    assert result.exit_code == 0


@pytest.mark.cli_integration
def test_reset_dirty_without_force_exits_nonzero(runner, standard_instance_toml, tmp_workspace, make_instance_worktrees):
    make_instance_worktrees(tmp_workspace, "feat-789")
    with patch("owm.cli.read_repo_state", return_value={"status": "dirty", "dirty": True}):
        result = runner.invoke(cli, [
            "--workspace", str(tmp_workspace), "reset", "feat-789", "--all",
        ])
    assert result.exit_code != 0
    assert "DIRTY_WORKTREE" in result.output


@pytest.mark.cli_integration
def test_reset_dirty_with_force_exits_zero(runner, standard_instance_toml, tmp_workspace, make_instance_worktrees):
    make_instance_worktrees(tmp_workspace, "feat-789")
    with patch("owm.cli.read_repo_state", return_value={"status": "dirty", "dirty": True}), \
         patch("owm.cli.git_reset_hard"):
        result = runner.invoke(cli, [
            "--workspace", str(tmp_workspace), "reset", "feat-789", "--all", "--force",
        ])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# owm regen-conf — instance.conf ownership guard (short-circuits before config load)
# ---------------------------------------------------------------------------

@pytest.mark.cli_integration
def test_regen_conf_skips_manual_conf(runner, tmp_workspace):
    """A conf marked '# owm: manual' is left untouched, with a note, not an error."""
    conf = tmp_workspace / "instances" / "feat-789" / "instance.conf"
    conf.parent.mkdir(parents=True, exist_ok=True)
    original = "# owm: manual\n[options]\nhttp_port = 9999\n"
    conf.write_text(original)
    result = runner.invoke(cli, ["--workspace", str(tmp_workspace), "regen-conf", "feat-789"])
    assert result.exit_code == 0
    assert "manually owned" in result.output + (result.stderr or "")
    assert conf.read_text() == original


@pytest.mark.cli_integration
def test_regen_conf_refuses_unmarked_conf(runner, tmp_workspace):
    """A conf with no ownership marker is refused (exit 1) rather than clobbered."""
    conf = tmp_workspace / "instances" / "feat-789" / "instance.conf"
    conf.parent.mkdir(parents=True, exist_ok=True)
    original = "[options]\nhttp_port = 9999\n"
    conf.write_text(original)
    result = runner.invoke(cli, ["--workspace", str(tmp_workspace), "regen-conf", "feat-789"])
    assert result.exit_code == 1
    assert "no ownership marker" in result.output + (result.stderr or "")
    assert conf.read_text() == original


@pytest.mark.cli_integration
def test_regen_conf_refuses_empty_addons_path(runner, standard_instance_toml, tmp_workspace):
    """regen-conf refuses (exit 1) when addons_path resolves to empty — writing a
    module-less Odoo conf would be worse than not regenerating."""
    (tmp_workspace / "workspace.toml").write_text(
        "[repos]\n"
        'odoo_like = "/dev/null"\n'
        'product_core = "/dev/null"\n'
        'customer_config = "/dev/null"\n'
        "[clusters]\n"
    )
    conf = tmp_workspace / "instances" / "feat-789" / "instance.conf"
    result = runner.invoke(cli, ["--workspace", str(tmp_workspace), "regen-conf", "feat-789"])
    assert result.exit_code == 1
    assert "load no modules" in result.output + (result.stderr or "")
    assert not conf.exists()


@pytest.mark.cli_integration
def test_validate_reports_empty_addons_path(runner, standard_instance_toml, tmp_workspace):
    """validate reports an empty-resolving addons_path as an error (exit 1), not a
    silent pass or a misleading 'out of sync — run regen-conf' warning."""
    (tmp_workspace / "workspace.toml").write_text(
        "[repos]\n"
        'odoo_like = "/dev/null"\n'
        'product_core = "/dev/null"\n'
        'customer_config = "/dev/null"\n'
        "[clusters]\n"
    )
    result = runner.invoke(cli, ["--workspace", str(tmp_workspace), "validate", "feat-789"])
    assert result.exit_code == 1
    out = result.output + (result.stderr or "")
    assert "load no modules" in out
    assert "out of sync" not in out  # not the misleading regen-conf nudge


@pytest.mark.cli_integration
def test_regen_conf_honors_repo_priority(runner, standard_instance_toml, tmp_workspace):
    """[defaults] repo_priority overrides [repos] declaration order in the generated
    addons_path. Guards the wiring from workspace config through to resolve_addons_path:
    module precedence is stated explicitly, not inferred from how repos happen to be listed."""
    # Declared odoo-first, but priority puts the override repos ahead of the base.
    (tmp_workspace / "workspace.toml").write_text(
        "[repos]\n"
        'odoo_like = {path = "/dev/null", has_addons = true}\n'
        'product_core = {path = "/dev/null", has_addons = true}\n'
        'customer_config = {path = "/dev/null", has_addons = true}\n'
        "[clusters]\n"
        "[defaults]\n"
        'repo_priority = ["customer_config", "product_core", "odoo_like"]\n'
    )
    result = runner.invoke(cli, ["--workspace", str(tmp_workspace), "regen-conf", "feat-789"])
    assert result.exit_code == 0
    conf = (tmp_workspace / "instances" / "feat-789" / "instance.conf").read_text()
    addons_line = next(line for line in conf.splitlines() if line.startswith("addons_path ="))
    # priority order wins over the odoo-first declaration order
    assert addons_line.index("customer_config") < addons_line.index("product_core") < addons_line.index("odoo_like")


def _make_module(worktree: Path, name: str):
    mod = worktree / name
    mod.mkdir(parents=True, exist_ok=True)
    (mod / "__manifest__.py").write_text("{'name': '%s'}\n" % name)


@pytest.mark.cli_integration
def test_validate_warns_when_feature_branch_lags_base(runner, standard_instance_toml, tmp_workspace):
    """A per-instance feature repo (base set) whose base worktree carries modules the
    branch lacks gets a lag warning naming them — staleness surfaced, not silently
    topped up from base the way owm did."""
    # product_core is "feat-789-dev:main" → non-shared, base=main
    feat = tmp_workspace / "instances" / "feat-789" / "product_core"
    base = tmp_workspace / "_shared" / "product_core" / "main"
    _make_module(feat, "alpha")
    _make_module(base, "alpha")
    _make_module(base, "beta")   # on base only — the lag
    result = runner.invoke(cli, ["--workspace", str(tmp_workspace), "validate", "feat-789"])
    out = result.output + (result.stderr or "")
    assert "product_core: base 'main' has 1 module(s) not on this feature branch (beta)" in out


@pytest.mark.cli_integration
def test_validate_no_lag_warning_when_branch_current(runner, standard_instance_toml, tmp_workspace):
    """No lag warning when the feature worktree already has every module its base has."""
    feat = tmp_workspace / "instances" / "feat-789" / "product_core"
    base = tmp_workspace / "_shared" / "product_core" / "main"
    _make_module(feat, "alpha")
    _make_module(base, "alpha")
    result = runner.invoke(cli, ["--workspace", str(tmp_workspace), "validate", "feat-789"])
    out = result.output + (result.stderr or "")
    assert "not on this feature branch" not in out


@pytest.mark.cli_integration
def test_cli_warns_when_cwd_in_different_workspace(runner, tmp_workspace, tmp_path, monkeypatch):
    """Operating on one workspace (--workspace/OWM_WORKSPACE) while standing inside
    another is allowed (the deliberate root wins) but warned about, so the shadowing
    isn't silent."""
    other = tmp_path / "other_ws"
    other.mkdir()
    (other / "workspace.toml").write_text("[repos]\n[clusters]\n")
    monkeypatch.chdir(other)
    result = runner.invoke(cli, ["--workspace", str(tmp_workspace), "list"])
    out = result.output + (result.stderr or "")
    assert "but cwd is inside a different workspace" in out
    assert str(other) in out


# ---------------------------------------------------------------------------
# branches --instance
# ---------------------------------------------------------------------------

@pytest.mark.cli_integration
def test_branches_instance_shows_repos(runner, tmp_workspace):
    from tests.conftest import instance_toml, FIXTURE_HTTP_PORT
    inst_dir = tmp_workspace / "instances" / "feat-789"
    inst_dir.mkdir(parents=True, exist_ok=True)
    (inst_dir / "instance.toml").write_text(instance_toml(
        repos={"odoo": "main:shared", "my_addon": "feat-789-dev:main"},
        db_name="owm_feat789",
        http_port=FIXTURE_HTTP_PORT,
    ))
    # create worktree dirs so repo_sync_status finds them (no real git needed for structure test)
    (tmp_workspace / "_shared" / "odoo" / "main").mkdir(parents=True, exist_ok=True)
    (inst_dir / "my_addon").mkdir(parents=True, exist_ok=True)

    result = runner.invoke(cli, ["--workspace", str(tmp_workspace),
                                 "branches", "--instance", "feat-789"])
    assert result.exit_code == 0
    assert "feat-789:" in result.output
    assert "odoo" in result.output
    assert "my_addon" in result.output


@pytest.mark.cli_integration
def test_branches_instance_shows_shared_and_owned_kind(runner, tmp_workspace):
    from tests.conftest import instance_toml, FIXTURE_HTTP_PORT
    inst_dir = tmp_workspace / "instances" / "feat-789"
    inst_dir.mkdir(parents=True, exist_ok=True)
    (inst_dir / "instance.toml").write_text(instance_toml(
        repos={"odoo": "main:shared", "my_addon": "feat-789-dev:main"},
        db_name="owm_feat789",
        http_port=FIXTURE_HTTP_PORT,
    ))
    (tmp_workspace / "_shared" / "odoo" / "main").mkdir(parents=True, exist_ok=True)
    (inst_dir / "my_addon").mkdir(parents=True, exist_ok=True)

    result = runner.invoke(cli, ["--workspace", str(tmp_workspace),
                                 "branches", "--instance", "feat-789"])
    assert result.exit_code == 0
    assert "shared" in result.output
    assert "owned" in result.output


@pytest.mark.cli_integration
def test_branches_instance_shows_branch_names(runner, tmp_workspace):
    from tests.conftest import instance_toml, FIXTURE_HTTP_PORT
    inst_dir = tmp_workspace / "instances" / "feat-789"
    inst_dir.mkdir(parents=True, exist_ok=True)
    (inst_dir / "instance.toml").write_text(instance_toml(
        repos={"odoo": "main:shared", "my_addon": "feat-789-dev:main"},
        db_name="owm_feat789",
        http_port=FIXTURE_HTTP_PORT,
    ))
    (tmp_workspace / "_shared" / "odoo" / "main").mkdir(parents=True, exist_ok=True)
    (inst_dir / "my_addon").mkdir(parents=True, exist_ok=True)

    result = runner.invoke(cli, ["--workspace", str(tmp_workspace),
                                 "branches", "--instance", "feat-789"])
    assert result.exit_code == 0
    assert "main" in result.output
    assert "feat-789-dev" in result.output
