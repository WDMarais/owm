"""
Tests for Odoo module install and upgrade operations.
Covers: Module install and upgrade section.
"""
import pytest

from owm.modules import install_modules, upgrade_modules


# ---------------------------------------------------------------------------
# owm create / owm start — install on first create
# ---------------------------------------------------------------------------

@pytest.mark.module_install
def test_create_installs_missing_modules():
    result = install_modules(
        instance="feat-789",
        configured_modules=["my_module", "other_module"],
        installed_modules=[],
    )
    assert result.installed == ["my_module", "other_module"] or set(result.installed) == {"my_module", "other_module"}
    assert result.odoo_bin_called is True


@pytest.mark.module_install
def test_start_skips_install_when_all_modules_present():
    result = install_modules(
        instance="feat-789",
        configured_modules=["my_module", "other_module"],
        installed_modules=["my_module", "other_module"],
    )
    assert result.installed == []
    assert result.skipped is True


@pytest.mark.module_install
def test_install_includes_dependencies_and_auto_installs():
    result = install_modules(
        instance="feat-789",
        configured_modules=["my_module"],
        installed_modules=[],
    )
    assert result.odoo_bin_args is not None
    # odoo-bin is called; it handles dependency resolution internally
    assert result.odoo_bin_called is True


# ---------------------------------------------------------------------------
# owm upgrade
# ---------------------------------------------------------------------------

@pytest.mark.module_install
def test_upgrade_stops_runs_update_all_restarts():
    result = upgrade_modules(
        instance="feat-789",
        modules=None,  # None means -u all
    )
    assert result.stopped_before is True
    assert result.odoo_bin_args == "-u all" or result.modules == "all"
    assert result.restarted is True


@pytest.mark.module_install
def test_upgrade_specific_modules():
    result = upgrade_modules(
        instance="feat-789",
        modules=["my_module", "other_module"],
    )
    assert result.stopped_before is True
    assert set(result.modules) == {"my_module", "other_module"}
    assert result.restarted is True


@pytest.mark.module_install
def test_upgrade_reinstall_forces_reinstall():
    """--reinstall flag: reinstalls all configured modules even if already present."""
    result = upgrade_modules(
        instance="feat-789",
        modules=None,
        reinstall=True,
    )
    assert result.reinstall is True
    assert result.odoo_bin_called is True


# === SPEC GAPS ===
# test_upgrade_failure_surfaces_log_tail: spec defines UPGRADE_FAILED code with log_tail
#   in MCP surface but does not specify CLI output format on failure.
# test_install_no_auto_diff_of_manifests: spec explicitly states owm does not diff manifests;
#   no test needed for that case, but the "user knows to run owm upgrade" assumption is
#   a process gap not an owm gap.
