"""
Tests for venv creation, stamp-based sync, rebuild, and patch application.
Covers: Venv management section.
"""
import pytest

# TODO: from owm.venv import create_venv, sync_venv_if_needed, rebuild_venv
# TODO: from owm.venv import compute_stamp, stamp_changed

def create_venv(*args, **kwargs):
    raise NotImplementedError

def sync_venv_if_needed(*args, **kwargs):
    raise NotImplementedError

def rebuild_venv(*args, **kwargs):
    raise NotImplementedError

def compute_stamp(*args, **kwargs):
    raise NotImplementedError

def stamp_changed(*args, **kwargs):
    raise NotImplementedError


# ---------------------------------------------------------------------------
# owm create — venv creation
# ---------------------------------------------------------------------------

@pytest.mark.venv_management
def test_create_venv_pins_python_version():
    result = create_venv(
        instance="feat-789",
        python_version="3.12",
        requirements_files=["odoo/requirements.txt"],
        patches=[],
        venv_dir="/ws/instances/feat-789/.venv",
    )  # TODO: wire up
    assert result.python_version == "3.12"
    assert result.created is True


@pytest.mark.venv_management
def test_create_venv_uses_uv():
    """uv is required, not optional — no pip fallback."""
    result = create_venv(
        instance="feat-789",
        python_version="3.12",
        requirements_files=["odoo/requirements.txt"],
        patches=[],
        venv_dir="/ws/instances/feat-789/.venv",
    )  # TODO: wire up
    assert result.tool == "uv"


@pytest.mark.venv_management
def test_create_venv_applies_workspace_patches():
    result = create_venv(
        instance="feat-789",
        python_version="3.12",
        requirements_files=["odoo/requirements.txt"],
        patches=["requirements_patches/odoo19_fix.txt"],
        venv_dir="/ws/instances/feat-789/.venv",
    )  # TODO: wire up
    assert result.patches_applied == ["requirements_patches/odoo19_fix.txt"]


@pytest.mark.venv_management
def test_create_venv_writes_stamp():
    """Stamp = hash of requirements + patch files; written after successful install."""
    result = create_venv(
        instance="feat-789",
        python_version="3.12",
        requirements_files=["odoo/requirements.txt"],
        patches=["requirements_patches/odoo19_fix.txt"],
        venv_dir="/ws/instances/feat-789/.venv",
    )  # TODO: wire up
    assert result.stamp is not None
    assert result.stamp_written is True


# ---------------------------------------------------------------------------
# Stamp computation
# ---------------------------------------------------------------------------

@pytest.mark.venv_management
def test_stamp_is_hash_of_requirements_and_patches():
    stamp1 = compute_stamp(
        requirements_files=["odoo/requirements.txt"],
        patches=["requirements_patches/fix.txt"],
    )  # TODO: wire up
    stamp2 = compute_stamp(
        requirements_files=["odoo/requirements.txt"],
        patches=["requirements_patches/fix.txt"],
    )  # TODO: wire up
    assert stamp1 == stamp2


@pytest.mark.venv_management
def test_stamp_differs_when_requirements_change():
    stamp1 = compute_stamp(requirements_files=["odoo/requirements.txt"], patches=[])  # TODO: wire up
    stamp2 = compute_stamp(requirements_files=["odoo/requirements_v2.txt"], patches=[])  # TODO: wire up
    assert stamp1 != stamp2


@pytest.mark.venv_management
def test_stamp_differs_when_patches_change():
    stamp1 = compute_stamp(requirements_files=["odoo/requirements.txt"], patches=[])  # TODO: wire up
    stamp2 = compute_stamp(requirements_files=["odoo/requirements.txt"], patches=["fix.txt"])  # TODO: wire up
    assert stamp1 != stamp2


# ---------------------------------------------------------------------------
# owm start — conditional sync
# ---------------------------------------------------------------------------

@pytest.mark.venv_management
def test_start_skips_venv_sync_when_stamp_unchanged():
    result = sync_venv_if_needed(
        venv_dir="/ws/instances/feat-789/.venv",
        current_stamp="abc123",
        recorded_stamp="abc123",
        requirements_files=["odoo/requirements.txt"],
        patches=[],
    )  # TODO: wire up
    assert result.synced is False
    assert result.reason == "stamp_unchanged"


@pytest.mark.venv_management
def test_start_syncs_venv_when_stamp_changed():
    result = sync_venv_if_needed(
        venv_dir="/ws/instances/feat-789/.venv",
        current_stamp="def456",
        recorded_stamp="abc123",
        requirements_files=["odoo/requirements.txt"],
        patches=[],
    )  # TODO: wire up
    assert result.synced is True
    assert result.stamp_updated is True


@pytest.mark.venv_management
def test_start_reapplies_patches_on_sync():
    result = sync_venv_if_needed(
        venv_dir="/ws/instances/feat-789/.venv",
        current_stamp="def456",
        recorded_stamp="abc123",
        requirements_files=["odoo/requirements.txt"],
        patches=["requirements_patches/odoo19_fix.txt"],
    )  # TODO: wire up
    assert result.patches_applied == ["requirements_patches/odoo19_fix.txt"]


# ---------------------------------------------------------------------------
# owm venv-rebuild
# ---------------------------------------------------------------------------

@pytest.mark.venv_management
def test_rebuild_deletes_and_recreates_venv():
    result = rebuild_venv(
        instance="feat-789",
        python_version="3.12",
        requirements_files=["odoo/requirements.txt"],
        patches=["requirements_patches/odoo19_fix.txt"],
        venv_dir="/ws/instances/feat-789/.venv",
    )  # TODO: wire up
    assert result.deleted is True
    assert result.created is True
    assert result.patches_applied == ["requirements_patches/odoo19_fix.txt"]
    assert result.stamp_written is True


@pytest.mark.venv_management
def test_rebuild_uses_uv():
    result = rebuild_venv(
        instance="feat-789",
        python_version="3.12",
        requirements_files=["odoo/requirements.txt"],
        patches=[],
        venv_dir="/ws/instances/feat-789/.venv",
    )  # TODO: wire up
    assert result.tool == "uv"


# === SPEC GAPS ===
# test_python_version_inferred_from_odoo_branch: spec says "inferred from Odoo branch if
#   absent" — inference logic (e.g., "19.0" → "3.12") is not specced; needs a lookup table.
# test_venv_no_pip_fallback: spec says no pip fallback "by default"; whether there is any
#   flag to enable pip fallback is not stated.
