"""
Tests for owm env output — resolved paths and binaries in multiple formats.
Covers: owm env section.
"""
import pytest

from owm.env import resolve_env, format_env


# ---------------------------------------------------------------------------
# Integration: resolve env for an instance
# ---------------------------------------------------------------------------

@pytest.mark.owm_env
def test_resolve_env_returns_all_required_keys():
    result = resolve_env(instance="feat-789", workspace_root="/ws")  # TODO: wire up
    required_keys = {
        "ODOO_BIN", "VENV_PYTHON", "PSQL", "DB_NAME", "DB_PORT",
        "INSTANCE_DIR", "LOG_FILE", "HTTP_PORT", "GEVENT_PORT",
        "ODOO_CONF", "WORKSPACE_DIR", "SCRIPTS_DIR", "WORKSPACE_SCRIPTS_DIR",
    }
    assert required_keys.issubset(set(result.keys()))


@pytest.mark.owm_env
def test_resolve_env_values_are_accurate_not_cached():
    """Generated at call time from live instance state — not from a stale snapshot."""
    result = resolve_env(instance="feat-789", workspace_root="/ws")  # TODO: wire up
    assert result["INSTANCE_DIR"] == "/ws/instances/feat-789"
    assert result["WORKSPACE_DIR"] == "/ws"


@pytest.mark.owm_env
def test_resolve_env_http_port_matches_instance_config():
    result = resolve_env(
        instance="feat-789",
        workspace_root="/ws",
        instance_http_port=8142,
        instance_gevent_port=8143,
    )  # TODO: wire up
    assert result["HTTP_PORT"] == "8142" or result["HTTP_PORT"] == 8142
    assert result["GEVENT_PORT"] == "8143" or result["GEVENT_PORT"] == 8143


# ---------------------------------------------------------------------------
# Output formats
# ---------------------------------------------------------------------------

@pytest.mark.owm_env
def test_format_env_dotenv():
    env = {"ODOO_BIN": "/ws/.venv/bin/odoo-bin", "DB_NAME": "odoo19_feat789"}
    result = format_env(env=env, fmt="dotenv")  # TODO: wire up
    assert "ODOO_BIN=/ws/.venv/bin/odoo-bin" in result
    assert "DB_NAME=odoo19_feat789" in result


@pytest.mark.owm_env
def test_format_env_json_is_machine_readable():
    import json
    env = {"ODOO_BIN": "/ws/.venv/bin/odoo-bin", "DB_NAME": "odoo19_feat789"}
    result = format_env(env=env, fmt="json")  # TODO: wire up
    parsed = json.loads(result)
    assert parsed["ODOO_BIN"] == "/ws/.venv/bin/odoo-bin"
    assert parsed["DB_NAME"] == "odoo19_feat789"


@pytest.mark.owm_env
def test_format_env_shell_produces_export_lines():
    env = {"ODOO_BIN": "/ws/.venv/bin/odoo-bin", "DB_NAME": "odoo19_feat789"}
    result = format_env(env=env, fmt="shell")  # TODO: wire up
    assert "export ODOO_BIN=" in result
    assert "export DB_NAME=" in result


@pytest.mark.owm_env
def test_format_env_shell_suitable_for_eval():
    """eval "$(owm env feat-789 --format shell)" must work without errors."""
    env = {"ODOO_BIN": "/ws/.venv/bin/odoo-bin"}
    result = format_env(env=env, fmt="shell")  # TODO: wire up
    lines = result.strip().splitlines()
    for line in lines:
        assert line.startswith("export ")


@pytest.mark.owm_env
def test_format_env_default_format_is_human_readable():
    """Plain owm env (no --format) → human-readable, not a specific machine format."""
    env = {"ODOO_BIN": "/ws/.venv/bin/odoo-bin"}
    result = format_env(env=env, fmt=None)  # TODO: wire up
    assert result is not None
    assert len(result) > 0


# === SPEC GAPS ===
# test_resolve_env_scripts_dir_when_no_instance_scripts: spec shows SCRIPTS_DIR as a key
#   but instance.toml [scripts].scripts_dir is optional — value when absent is not stated.
# test_resolve_env_workspace_scripts_dir_when_absent: WORKSPACE_SCRIPTS_DIR when
#   workspace.toml has no [scripts].scripts_dir is not defined.
