"""
Tests for install_instance_modules — the shared orchestration behind
`owm install` (CLI) and `owm_install` (MCP). The Odoo spawn + DB query are
patched; the manifest-append and result shaping run for real.
"""
from unittest.mock import patch

import pytest

from owm.errors import OwmError, INSTANCE_RUNNING
from owm.instance import install_instance_modules

from tests.conftest import instance_toml, FIXTURE_HTTP_PORT


def _write_instance(workspace_root, instance, *, modules=None):
    inst_dir = workspace_root / "instances" / instance
    inst_dir.mkdir(parents=True, exist_ok=True)
    (inst_dir / "instance.toml").write_text(
        instance_toml(
            repos={"product_core": "feat-1-dev:main"},
            db_name=f"owm_test_{instance}",
            http_port=FIXTURE_HTTP_PORT,
            modules=modules,
        )
    )


def test_raises_when_no_modules_given_or_declared(tmp_workspace):
    _write_instance(tmp_workspace, "feat-1", modules=None)
    with pytest.raises(OwmError) as ei:
        install_instance_modules("feat-1", str(tmp_workspace))
    assert ei.value.code == "NO_MODULES"


def test_refuses_when_instance_running(tmp_workspace):
    _write_instance(tmp_workspace, "feat-1", modules=["sale"])
    with patch("owm.instance._read_pid", return_value=4321), \
         patch("owm.instance._process_alive", return_value=True):
        with pytest.raises(OwmError) as ei:
            install_instance_modules("feat-1", str(tmp_workspace), ["sale"])
    assert ei.value.code == INSTANCE_RUNNING


def test_installs_missing_and_saves_to_manifest(tmp_workspace):
    _write_instance(tmp_workspace, "feat-1", modules=None)
    with patch("owm.instance._query_installed_modules", return_value=[]), \
         patch("owm.instance.start_instance") as start, \
         patch("owm.instance.stop_instance") as stop, \
         patch("owm.instance.pin_web_base_url"):
        result = install_instance_modules("feat-1", str(tmp_workspace), ["sale", "purchase"])

    assert result.status == "installed"
    assert result.installed == ["sale", "purchase"]
    assert result.saved == ["sale", "purchase"]
    start.assert_called_once()
    stop.assert_called_once()

    # manifest was appended for real
    import tomllib
    toml = (tmp_workspace / "instances" / "feat-1" / "instance.toml").read_text()
    assert set(tomllib.loads(toml)["install"]["modules"]) == {"sale", "purchase"}


def test_skips_install_when_all_present_and_can_opt_out_of_save(tmp_workspace):
    _write_instance(tmp_workspace, "feat-1", modules=None)
    with patch("owm.instance._query_installed_modules", return_value=["sale"]), \
         patch("owm.instance.start_instance") as start, \
         patch("owm.instance.stop_instance"), \
         patch("owm.instance.pin_web_base_url"):
        result = install_instance_modules(
            "feat-1", str(tmp_workspace), ["sale"], save=False,
        )

    assert result.status == "nothing_to_install"
    assert result.already_installed == ["sale"]
    assert result.installed == []
    assert result.saved == []
    start.assert_not_called()

    import tomllib
    toml = (tmp_workspace / "instances" / "feat-1" / "instance.toml").read_text()
    assert "install" not in tomllib.loads(toml)  # save=False left manifest alone


def test_owm_install_mcp_delegates_and_shapes_result(tmp_workspace):
    import owm.mcp as mcp
    _write_instance(tmp_workspace, "feat-1", modules=None)
    with patch("owm.instance._query_installed_modules", return_value=[]), \
         patch("owm.instance.start_instance"), \
         patch("owm.instance.stop_instance"), \
         patch("owm.instance.pin_web_base_url"):
        out = mcp.owm_install("feat-1", ["sale"])
    assert out == {
        "status": "installed",
        "installed": ["sale"],
        "already_installed": [],
        "saved": ["sale"],
    }
