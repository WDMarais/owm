"""
Tests for the owm.log audit trail.
Covers: owm.log — audit trail section.
"""
import pytest

from owm.audit_log import append_log_entry, read_log_tail, parse_log_entry


# ---------------------------------------------------------------------------
# Log structure
# ---------------------------------------------------------------------------

@pytest.mark.audit_log
def test_start_appends_structured_entry():
    entry = append_log_entry(
        log_path="/ws/owm.log",
        operation="start",
        instance="feat-789",
        result="spawned",
        pid=1234,
    )
    assert entry["timestamp"] is not None
    assert entry["operation"] == "start"
    assert entry["instance"] == "feat-789"
    assert entry["result"] == "spawned"
    assert entry["pid"] == 1234


@pytest.mark.audit_log
def test_script_run_appends_structured_entry():
    entry = append_log_entry(
        log_path="/ws/owm.log",
        operation="run-script",
        instance="feat-789",
        script="run",
        result="ok",
        summary={"ok": 8, "fail": 0, "warn": 0, "none": 2, "total": 10},
    )
    assert entry["operation"] == "run-script"
    assert entry["summary"]["total"] == 10


@pytest.mark.audit_log
def test_log_is_append_only(tmp_path):
    """Each entry appended, never overwrites previous content."""
    log = str(tmp_path / "owm.log")
    append_log_entry(log_path=log, operation="start", instance="a", result="spawned", pid=1)
    append_log_entry(log_path=log, operation="stop", instance="a", result="stopped", pid=1)
    tail = read_log_tail(log_path=log, n=10)
    assert len(tail) == 2


@pytest.mark.audit_log
def test_log_is_structured_json_per_line():
    entry_raw = '{"timestamp": "2026-05-16T09:00:00", "operation": "start", "instance": "feat-789", "result": "spawned", "pid": 1234}'
    entry = parse_log_entry(entry_raw)
    assert entry["operation"] == "start"
    assert entry["instance"] == "feat-789"


@pytest.mark.audit_log
def test_log_independent_of_dashboard():
    """owm.log is written regardless of whether dashboard is open."""
    entry = append_log_entry(
        log_path="/ws/owm.log",
        operation="start",
        instance="feat-789",
        result="spawned",
        pid=1234,
        dashboard_open=False,
    )
    assert entry is not None


@pytest.mark.audit_log
def test_log_captures_cli_and_ui_and_agent_operations():
    """owm.log records operations regardless of source: CLI, dashboard, or agent."""
    for source in ("cli", "dashboard", "agent"):
        entry = append_log_entry(
            log_path="/ws/owm.log",
            operation="start",
            instance="feat-789",
            result="spawned",
            pid=1234,
            source=source,
        )
        assert entry is not None


@pytest.mark.audit_log
def test_log_read_tail_returns_n_lines(tmp_path):
    log = str(tmp_path / "owm.log")
    for i in range(200):
        append_log_entry(log_path=log, operation="start", instance=f"inst-{i}", result="spawned")
    tail = read_log_tail(log_path=log, n=50)
    assert len(tail) == 50


# ---------------------------------------------------------------------------
# Log rotation
# ---------------------------------------------------------------------------

# (Rotation tests are in test_cli_commands.py — see check_rotation_needed / rotate_log)

# === SPEC GAPS ===
# test_log_port_eviction_entry: spec says "port evictions" are captured in owm.log;
#   the exact entry shape for eviction is not shown (only start/script-run shapes are shown).
# test_log_template_sync_entry: spec says "template sync attempts" are captured; entry
#   shape not shown.
# test_log_tail_survives_page_reload: spec says dashboard "reads from file, not JS state";
#   this is a dashboard integration property, not a unit test concern.
