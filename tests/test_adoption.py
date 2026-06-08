"""
Tests for process adoption (adopt_process + adopt_instance wiring).
"""
import json
import pytest

from owm.adoption import adopt_process
from owm.operations import adopt_instance


# ---------------------------------------------------------------------------
# Adoption
# ---------------------------------------------------------------------------

@pytest.mark.adoption
def test_adopt_links_process_to_instance():
    result = adopt_process(
        instance="feat-789",
        pid=9999,
        configured_port=8142,
        process_port=8142,
    )
    assert result.status == "adopted"
    assert result.pid == 9999
    assert result.pid_written_to_state is True


@pytest.mark.adoption
def test_adopt_makes_instance_manageable_via_stop_kill_health():
    """After adoption, owm stop/kill/health work on the adopted process."""
    result = adopt_process(
        instance="feat-789",
        pid=9999,
        configured_port=8142,
        process_port=8142,
    )
    assert result.manageable is True


@pytest.mark.adoption
def test_adopt_port_mismatch_warns_requires_force():
    result = adopt_process(
        instance="feat-789",
        pid=9999,
        configured_port=8142,
        process_port=8150,
        force=False,
    )
    assert result.status == "needs_confirmation"
    assert result.warning is not None
    assert "port" in result.warning.lower()


@pytest.mark.adoption
def test_adopt_port_mismatch_force_proceeds():
    result = adopt_process(
        instance="feat-789",
        pid=9999,
        configured_port=8142,
        process_port=8150,
        force=True,
    )
    assert result.status == "adopted"



# ---------------------------------------------------------------------------
# adopt_instance — wiring (writes state.json)
# ---------------------------------------------------------------------------

@pytest.mark.adoption
def test_adopt_instance_writes_pid_to_state(standard_instance_toml, tmp_workspace):
    state_path = tmp_workspace / "instances" / "feat-789" / "state.json"
    result = adopt_instance(
        "feat-789", 9999, str(tmp_workspace),
        configured_port=18142,
        process_port=18142,
    )
    assert result.status == "adopted"
    assert json.loads(state_path.read_text())["pid"] == 9999


@pytest.mark.adoption
def test_adopt_instance_port_mismatch_does_not_write_state(standard_instance_toml, tmp_workspace):
    state_path = tmp_workspace / "instances" / "feat-789" / "state.json"
    result = adopt_instance(
        "feat-789", 9999, str(tmp_workspace),
        configured_port=18142,
        process_port=18150,
    )
    assert result.status == "needs_confirmation"
    assert not state_path.exists()


@pytest.mark.adoption
def test_adopt_instance_force_port_mismatch_writes_state(standard_instance_toml, tmp_workspace):
    state_path = tmp_workspace / "instances" / "feat-789" / "state.json"
    result = adopt_instance(
        "feat-789", 9999, str(tmp_workspace),
        configured_port=18142,
        process_port=18150,
        force=True,
    )
    assert result.status == "adopted"
    assert json.loads(state_path.read_text())["pid"] == 9999
