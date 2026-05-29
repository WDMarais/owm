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
def test_rename_stopped_exits_zero_with_output(runner, tmp_workspace):
    with patch("owm.cli._is_running", return_value=False):
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
    (inst_dir / "instance.log").write_text("\n".join(json.dumps(l) for l in lines) + "\n")
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
    (inst_dir / "instance.log").write_text("\n".join(json.dumps(l) for l in lines) + "\n")
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
    with patch("owm.cli.git_fetch_bare", return_value=True):
        result = runner.invoke(cli, ["--workspace", str(tmp_workspace), "fetch"])
    assert result.exit_code == 0
    assert "odoo" in result.output
    assert "updated" in result.output


@pytest.mark.cli_integration
def test_fetch_repo_timeout_prints_warning(runner, tmp_workspace):
    (tmp_workspace / "workspace.toml").write_text('[repos]\nodoo = "git@example.com:odoo.git"\n[clusters]\n')
    (tmp_workspace / "_repos" / "odoo.git").mkdir(parents=True, exist_ok=True)
    from owm.errors import OwmError, FETCH_TIMEOUT
    with patch("owm.cli.git_fetch_bare", side_effect=OwmError("fetch timed out after 30s", code=FETCH_TIMEOUT)):
        result = runner.invoke(cli, ["--workspace", str(tmp_workspace), "fetch"])
    assert result.exit_code == 0
    assert "warning" in result.output
    assert "FETCH_TIMEOUT" in result.output


@pytest.mark.cli_integration
def test_fetch_repo_no_update_says_up_to_date(runner, tmp_workspace):
    (tmp_workspace / "workspace.toml").write_text('[repos]\nodoo = "git@example.com:odoo.git"\n[clusters]\n')
    (tmp_workspace / "_repos" / "odoo.git").mkdir(parents=True, exist_ok=True)
    with patch("owm.cli.git_fetch_bare", return_value=False):
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
