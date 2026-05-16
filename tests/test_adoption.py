"""
Tests for unmanaged process detection and adoption.
Covers: Unmanaged processes and adoption section.
"""
import pytest

# TODO: from owm.adoption import detect_unmanaged_processes, adopt_process, status_with_unmanaged

def detect_unmanaged_processes(*args, **kwargs):
    raise NotImplementedError

def adopt_process(*args, **kwargs):
    raise NotImplementedError

def status_with_unmanaged(*args, **kwargs):
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

@pytest.mark.adoption
def test_status_surfaces_unmanaged_odoo_processes():
    result = status_with_unmanaged(
        configured_instances={"feat-789": {"http_port": 8142, "db_name": "odoo19_feat789"}},
        running_processes=[
            {"pid": 9999, "port": 8143, "cmdline": "python odoo-bin --http-port 8143"},
        ],
    )  # TODO: wire up
    assert any(p["pid"] == 9999 for p in result.unmanaged)


@pytest.mark.adoption
def test_unmanaged_on_configured_port_surfaced_with_adopt_prompt():
    """Unmanaged process on feat-789's port → 'adopt or kill?' message."""
    result = status_with_unmanaged(
        configured_instances={"feat-789": {"http_port": 8142}},
        running_processes=[
            {"pid": 9999, "port": 8142, "cmdline": "python odoo-bin --http-port 8142"},
        ],
    )  # TODO: wire up
    entry = next(p for p in result.instance_conflicts if p["instance"] == "feat-789")
    assert entry["unmanaged_pid"] == 9999
    assert "adopt" in entry["message"].lower() or "kill" in entry["message"].lower()


@pytest.mark.adoption
def test_unmanaged_no_matching_instance_shown_without_adopt_option():
    """Unmanaged process on port not matching any instance → shown, no adopt available."""
    result = status_with_unmanaged(
        configured_instances={"feat-789": {"http_port": 8142}},
        running_processes=[
            {"pid": 8888, "port": 9999, "cmdline": "python odoo-bin --http-port 9999"},
        ],
    )  # TODO: wire up
    orphan = next(p for p in result.unmanaged if p["pid"] == 8888)
    assert orphan["adopt_available"] is False


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
    )  # TODO: wire up
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
    )  # TODO: wire up
    assert result.manageable is True


@pytest.mark.adoption
def test_adopt_port_mismatch_warns_requires_force():
    result = adopt_process(
        instance="feat-789",
        pid=9999,
        configured_port=8142,
        process_port=8150,
        force=False,
    )  # TODO: wire up
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
    )  # TODO: wire up
    assert result.status == "adopted"


# === SPEC GAPS ===
# test_adopt_mcp_tool: spec notes owm_adopt is not listed in MCP tools (Deferred section);
#   no MCP test written for adoption.
# test_unmanaged_detection_method: spec says "owm processes" but does not specify whether
#   detection scans /proc, uses ps, or inspects port bindings — implementation-defined.
