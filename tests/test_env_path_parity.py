"""
Env-surface parity + the find_odoo_repo finding contract.

1. CLI `owm env` and MCP `owm_env` resolve ODOO_BIN to the same path. Regression
   guard for the drift where CLI resolved <instance>/.venv/bin/odoo-bin (ignoring
   the shared flag and the worktree) while MCP went through the worktree. Both
   now go through instance.odoo_bin_path.
2. When odoo_repo is unset and a repo named 'odoo' is assumed, find_odoo_repo
   returns an INFO Finding instead of printing. The lib writes to no stream:
   CLI stdout stays pure (parseable JSON), the note goes to stderr; MCP keeps
   env self-contained under "env" and carries the note under "findings".

Exercised against a real on-disk instance.toml, no mocks.
"""
import json

import pytest
from click.testing import CliRunner

from owm.cli import cli
from owm.mcp import owm_env
from owm.errors import NO_ODOO_REPO, Severity


@pytest.fixture
def runner():
    return CliRunner()


def _write_instance(runner, tmp_workspace, spec):
    result = runner.invoke(cli, [
        "--workspace", str(tmp_workspace),
        "create", "feat-789", spec, "--toml-only",
    ])
    assert result.exit_code == 0, result.output


def _cli_env(runner, tmp_workspace):
    return runner.invoke(cli, [
        "--workspace", str(tmp_workspace),
        "env", "feat-789", "--format", "json",
    ])


def _cli_odoo_bin(runner, tmp_workspace):
    result = _cli_env(runner, tmp_workspace)
    assert result.exit_code == 0, result.output
    # stdout only: any resolution note goes to stderr and must not pollute the
    # machine-readable env.
    return json.loads(result.stdout)["ODOO_BIN"]


@pytest.mark.owm_env
def test_cli_and_mcp_agree_per_instance_odoo(runner, tmp_workspace):
    """Per-instance odoo (shared=false): both surfaces point at the instance worktree."""
    _write_instance(runner, tmp_workspace, "odoo=feat-789:main")

    cli_bin = _cli_odoo_bin(runner, tmp_workspace)
    mcp_bin = owm_env("feat-789")["env"]["ODOO_BIN"]
    expected = str(tmp_workspace / "instances" / "feat-789" / "odoo" / "odoo-bin")

    assert cli_bin == mcp_bin == expected


@pytest.mark.owm_env
def test_cli_and_mcp_agree_shared_odoo(runner, tmp_workspace):
    """Shared odoo: both surfaces point at the _shared worktree, not the venv."""
    _write_instance(runner, tmp_workspace, "odoo=main:shared")

    cli_bin = _cli_odoo_bin(runner, tmp_workspace)
    mcp_bin = owm_env("feat-789")["env"]["ODOO_BIN"]
    expected = str(tmp_workspace / "_shared" / "odoo" / "main" / "odoo-bin")

    assert cli_bin == mcp_bin == expected


@pytest.mark.owm_env
def test_assumed_odoo_surfaces_as_finding_not_a_print(runner, tmp_workspace):
    """odoo_repo unset + a repo named 'odoo': an INFO finding, never a stream write."""
    _write_instance(runner, tmp_workspace, "odoo=feat-789:main")

    # CLI: stdout parses cleanly (no note bleed); the note is on stderr.
    result = _cli_env(runner, tmp_workspace)
    json.loads(result.stdout)  # no JSONDecodeError "Extra data"
    assert "findings" not in result.stdout
    assert "assuming repo 'odoo'" in result.stderr

    # MCP: env self-contained, finding carried alongside under its own key.
    env_result = owm_env("feat-789")
    assert set(env_result) == {"env", "findings"}
    assert "ODOO_BIN" in env_result["env"]
    assert "findings" not in env_result["env"]
    (finding,) = env_result["findings"]
    assert finding["code"] == NO_ODOO_REPO
    assert finding["severity"] == Severity.INFO


@pytest.mark.owm_env
def test_shared_odoo_emits_no_finding(runner, tmp_workspace):
    """A clean single-shared-repo resolution carries no findings."""
    _write_instance(runner, tmp_workspace, "odoo=main:shared")

    env_result = owm_env("feat-789")
    assert env_result["findings"] == []
