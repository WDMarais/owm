"""
Smoke tests for venv operations — real uv subprocesses, real filesystem.
Covers: create_venv, sync_venv_if_needed, rebuild_venv.
"""
import os
import pytest

from owm.venv import create_venv, sync_venv_if_needed, rebuild_venv, _read_stamp, compute_stamp


@pytest.mark.smoke
def test_smoke_create_venv_creates_python_binary(tmp_path):
    venv_dir = str(tmp_path / ".venv")
    result = create_venv(
        instance="smoke-test",
        python_version="3.12",
        requirements_files=[],
        patches=[],
        venv_dir=venv_dir,
    )
    assert result.created is True
    assert os.path.isfile(os.path.join(venv_dir, "bin", "python"))


@pytest.mark.smoke
def test_smoke_create_venv_writes_stamp_file(tmp_path):
    venv_dir = str(tmp_path / ".venv")
    result = create_venv(
        instance="smoke-test",
        python_version="3.12",
        requirements_files=[],
        patches=[],
        venv_dir=venv_dir,
    )
    assert result.stamp_written is True
    on_disk = _read_stamp(venv_dir)
    assert on_disk == result.stamp


@pytest.mark.smoke
def test_smoke_sync_venv_skips_when_stamp_unchanged(tmp_path):
    venv_dir = str(tmp_path / ".venv")
    create_venv(
        instance="smoke-test",
        python_version="3.12",
        requirements_files=[],
        patches=[],
        venv_dir=venv_dir,
    )
    stamp = compute_stamp([], [])
    result = sync_venv_if_needed(
        venv_dir=venv_dir,
        current_stamp=stamp,
        recorded_stamp=stamp,
        requirements_files=[],
        patches=[],
    )
    assert result.synced is False
    assert result.reason == "stamp_unchanged"


@pytest.mark.smoke
def test_smoke_sync_venv_updates_stamp_when_changed(tmp_path):
    venv_dir = str(tmp_path / ".venv")
    create_venv(
        instance="smoke-test",
        python_version="3.12",
        requirements_files=[],
        patches=[],
        venv_dir=venv_dir,
    )
    new_stamp = "newhash12345678"
    result = sync_venv_if_needed(
        venv_dir=venv_dir,
        current_stamp=new_stamp,
        recorded_stamp="oldhash12345678",
        requirements_files=[],
        patches=[],
    )
    assert result.synced is True
    assert _read_stamp(venv_dir) == new_stamp


@pytest.mark.smoke
def test_smoke_rebuild_venv_recreates(tmp_path):
    venv_dir = str(tmp_path / ".venv")
    create_venv(
        instance="smoke-test",
        python_version="3.12",
        requirements_files=[],
        patches=[],
        venv_dir=venv_dir,
    )
    result = rebuild_venv(
        instance="smoke-test",
        python_version="3.12",
        requirements_files=[],
        patches=[],
        venv_dir=venv_dir,
    )
    assert result.deleted is True
    assert result.created is True
    assert os.path.isfile(os.path.join(venv_dir, "bin", "python"))
