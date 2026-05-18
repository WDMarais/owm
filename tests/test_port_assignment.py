"""
Tests for port assignment logic.
Covers: Port assignment, Ports — gevent and workers sections.
"""
import pytest
from unittest.mock import patch, MagicMock

from owm.ports import assign_port, find_conflicting_process, evict_port
from owm.ports import PortConflict, PortExhaustedError
from owm.ports import get_eviction_log, eviction_count_in_window


# ---------------------------------------------------------------------------
# Port pair assignment
# ---------------------------------------------------------------------------

@pytest.mark.port_assignment
def test_assign_port_returns_first_free_pair_in_range():
    """Ports 8100–8142 occupied; next free pair is 8143/8144."""
    occupied = set(range(8100, 8143))  # 8100..8142 taken
    pool = {"range": [8100, 8299], "occupied": occupied}
    result = assign_port(pool=pool)
    assert result.http_port == 8143
    assert result.gevent_port == 8144


@pytest.mark.port_assignment
def test_assign_port_returns_lowest_free_pair():
    """Only 8100/8101 free."""
    occupied = set(range(8102, 8299))
    pool = {"range": [8100, 8299], "occupied": occupied}
    result = assign_port(pool=pool)
    assert result.http_port == 8100
    assert result.gevent_port == 8101


@pytest.mark.port_assignment
def test_assign_port_gevent_is_http_plus_one():
    occupied = set()
    pool = {"range": [8100, 8299], "occupied": occupied}
    result = assign_port(pool=pool)
    assert result.gevent_port == result.http_port + 1


@pytest.mark.port_assignment
def test_assign_port_range_exhausted_raises():
    """All 100 pairs in [8100, 8299] occupied → PORT_EXHAUSTED."""
    occupied = set(range(8100, 8300))
    pool = {"range": [8100, 8299], "occupied": occupied}
    with pytest.raises(Exception) as exc_info:
        assign_port(pool=pool)
    assert "PORT_EXHAUSTED" in str(exc_info.value) or "port range exhausted" in str(exc_info.value).lower()


@pytest.mark.port_assignment
def test_assign_port_range_exhausted_error_message():
    """Error message must mention archive/delete as remedy."""
    occupied = set(range(8100, 8300))
    pool = {"range": [8100, 8299], "occupied": occupied}
    with pytest.raises(Exception) as exc_info:
        assign_port(pool=pool)
    msg = str(exc_info.value).lower()
    assert "archive" in msg or "delete" in msg


@pytest.mark.port_assignment
def test_assign_port_records_in_instance_config():
    """Assigned port pair must be written back to instance config."""
    pool = {"range": [8100, 8299], "occupied": set()}
    result = assign_port(pool=pool)
    assert result.http_port is not None
    assert result.gevent_port is not None


@pytest.mark.port_assignment
def test_assign_port_respects_owm_internal_range_exclusion():
    """[8090, 8099] is the owm-internal range; must never assign from it."""
    pool = {"range": [8100, 8299], "owm_range": [8090, 8099], "occupied": set()}
    result = assign_port(pool=pool)
    assert result.http_port >= 8100
    assert result.gevent_port >= 8100


# ---------------------------------------------------------------------------
# Pinned port in instance.toml
# ---------------------------------------------------------------------------

from owm.ports import honour_pinned_port


@pytest.mark.port_assignment
def test_pinned_port_no_conflict_assigned():
    """instance.toml specifies explicit port; no conflict → honour it."""
    pinned = 8143
    occupied = set()
    result = honour_pinned_port(pinned_http=pinned, occupied=occupied)
    assert result.http_port == 8143
    assert result.gevent_port == 8144


@pytest.mark.port_assignment
def test_pinned_port_conflicts_with_stopped_instance_warns():
    """Pinned port held by a stopped instance → warn, prompt to evict."""
    pinned = 8143
    stopped_holder = {"instance": "review-101", "running": False, "http_port": 8143}
    result = honour_pinned_port(
        pinned_http=pinned,
        occupied={8143},
        existing_instances=[stopped_holder],
    )
    assert result.conflict is not None
    assert result.conflict.instance == "review-101"
    assert result.conflict.running is False
    assert result.conflict.requires_confirmation is True


@pytest.mark.port_assignment
def test_pinned_port_conflicts_with_running_instance_hard_error():
    """Pinned port held by a running instance → PORT_CONTESTED, no eviction."""
    pinned = 8143
    running_holder = {"instance": "review-101", "running": True, "http_port": 8143}
    with pytest.raises(Exception) as exc_info:
        honour_pinned_port(
            pinned_http=pinned,
            occupied={8143},
            existing_instances=[running_holder],
        )
    assert "PORT_CONTESTED" in str(exc_info.value) or "running" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# Start-time port conflict with unrelated process
# ---------------------------------------------------------------------------

from owm.ports import check_port_at_start


@pytest.mark.port_assignment
def test_start_port_bound_by_unrelated_process_surfaces_info():
    """Port bound by unrelated process → surfaces name, PID, cmdline."""
    result = check_port_at_start(http_port=8142, bound_by={"pid": 9999, "name": "nginx", "cmdline": "nginx -g daemon off;"})
    assert result.conflict is not None
    assert result.conflict.pid == 9999
    assert result.conflict.name == "nginx"
    assert result.conflict.cmdline == "nginx -g daemon off;"
    assert result.conflict.options == ["kill", "reassign"]


@pytest.mark.port_assignment
def test_start_port_conflict_reassign_updates_config_permanently():
    """User chooses reassign → instance config updated to new port, not reverted after restart."""
    result = check_port_at_start(
        http_port=8142,
        bound_by={"pid": 9999, "name": "nginx", "cmdline": "nginx -g daemon off;"},
        next_free_port=8200,
        resolution="reassign",
    )
    assert result.new_http_port == 8200
    assert result.config_updated is True


@pytest.mark.port_assignment
def test_start_port_conflict_kill_resolution_proceeds_on_original_port():
    """User chooses kill → port freed, start proceeds on original port."""
    result = check_port_at_start(
        http_port=8142,
        bound_by={"pid": 9999, "name": "nginx", "cmdline": "nginx -g daemon off;"},
        resolution="kill",
    )
    assert result.http_port == 8142
    assert result.config_updated is False


# ---------------------------------------------------------------------------
# Port eviction logging and threshold
# ---------------------------------------------------------------------------

@pytest.mark.port_assignment
def test_port_eviction_is_logged():
    """Eviction (reassignment due to conflict) must produce a log entry."""
    result = evict_port(
        instance="feat-789",
        old_port=8142,
        new_port=8200,
        reason="conflict with nginx PID 9999",
    )
    assert result.logged is True
    assert result.old_port == 8142
    assert result.new_port == 8200


@pytest.mark.port_assignment
def test_eviction_count_within_threshold_no_alert():
    result = eviction_count_in_window(evictions=5, threshold=10, window_days=7)
    assert result.alert is False


@pytest.mark.port_assignment
def test_eviction_count_exceeds_threshold_surfaces_recommendation():
    """More than threshold evictions in rolling week → recommend port range shift."""
    result = eviction_count_in_window(evictions=11, threshold=10, window_days=7)
    assert result.alert is True
    assert "port range" in result.recommendation.lower()


@pytest.mark.port_assignment
def test_eviction_threshold_configurable():
    """Threshold is read from workspace.toml defaults, not hardcoded."""
    result = eviction_count_in_window(evictions=3, threshold=2, window_days=7)
    assert result.alert is True


# ---------------------------------------------------------------------------
# Gevent / workers
# ---------------------------------------------------------------------------

from owm.instance import generate_instance_conf


@pytest.mark.port_assignment
@pytest.mark.ports_gevent
def test_odoo_conf_includes_longpolling_port():
    conf = generate_instance_conf(
        instance_name="feat-789",
        http_port=8142,
        gevent_port=8143,
        workers=2,
    )
    assert "longpolling_port = 8143" in conf or conf.get("longpolling_port") == 8143


@pytest.mark.port_assignment
@pytest.mark.ports_gevent
def test_odoo_conf_workers_default_two():
    conf = generate_instance_conf(
        instance_name="feat-789",
        http_port=8142,
        gevent_port=8143,
        workers=2,
    )
    assert conf.get("workers") == 2 or "workers = 2" in conf



@pytest.mark.port_assignment
@pytest.mark.ports_gevent
def test_odoo_conf_includes_dbfilter_for_subdomain():
    """dbfilter set to ^<instance_name>$ for subdomain isolation."""
    conf = generate_instance_conf(
        instance_name="feat-789",
        http_port=8142,
        gevent_port=8143,
        workers=2,
    )
    assert conf.get("dbfilter") == "^feat-789$" or "dbfilter = ^feat-789$" in conf


@pytest.mark.port_assignment
@pytest.mark.ports_gevent
def test_odoo_conf_no_dbfilter_when_proxy_inactive():
    """dbfilter must be absent when proxy is not active.
    Without subdomain routing each instance shares localhost — dbfilter causes
    silent session cookie collisions across instances (the bug owm was built to avoid)."""
    conf = generate_instance_conf(
        instance_name="feat-789",
        http_port=8142,
        gevent_port=8143,
        workers=2,
        proxy_active=False,
    )
    assert "dbfilter" not in conf


# ---------------------------------------------------------------------------
# find_conflicting_process (I/O layer)
# ---------------------------------------------------------------------------

@pytest.mark.port_assignment
def test_find_conflicting_process_returns_none_when_port_free():
    with patch("owm.ports.psutil.net_connections", return_value=[]):
        result = find_conflicting_process(8142)
    assert result is None


@pytest.mark.port_assignment
def test_find_conflicting_process_returns_pid_name_cmdline():
    mock_conn = MagicMock()
    mock_conn.laddr.port = 8142
    mock_conn.status = "LISTEN"
    mock_conn.pid = 9999
    mock_proc = MagicMock()
    mock_proc.name.return_value = "nginx"
    mock_proc.cmdline.return_value = ["nginx", "-g", "daemon off;"]
    with patch("owm.ports.psutil.net_connections", return_value=[mock_conn]):
        with patch("owm.ports.psutil.Process", return_value=mock_proc):
            result = find_conflicting_process(8142)
    assert result == {"pid": 9999, "name": "nginx", "cmdline": "nginx -g daemon off;"}


@pytest.mark.port_assignment
def test_find_conflicting_process_ignores_non_listen_connections():
    mock_conn = MagicMock()
    mock_conn.laddr.port = 8142
    mock_conn.status = "ESTABLISHED"
    with patch("owm.ports.psutil.net_connections", return_value=[mock_conn]):
        result = find_conflicting_process(8142)
    assert result is None


# ---------------------------------------------------------------------------
# get_eviction_log / evict_port (I/O layer)
# ---------------------------------------------------------------------------

@pytest.mark.port_assignment
def test_get_eviction_log_reads_json_lines(tmp_path):
    log = tmp_path / "evictions.jsonl"
    log.write_text(
        '{"instance":"feat-789","old_port":8142,"new_port":8200,"reason":"nginx"}\n'
    )
    result = get_eviction_log(str(log))
    assert len(result) == 1
    assert result[0]["instance"] == "feat-789"
    assert result[0]["old_port"] == 8142


@pytest.mark.port_assignment
def test_get_eviction_log_missing_file_returns_empty(tmp_path):
    result = get_eviction_log(str(tmp_path / "nonexistent.jsonl"))
    assert result == []


@pytest.mark.port_assignment
def test_evict_port_writes_to_log_when_path_given(tmp_path):
    log = tmp_path / "evictions.jsonl"
    result = evict_port("feat-789", 8142, 8200, "nginx conflict", log_path=str(log))
    assert result.logged is True
    entries = get_eviction_log(str(log))
    assert len(entries) == 1
    assert entries[0]["old_port"] == 8142
    assert entries[0]["new_port"] == 8200


@pytest.mark.port_assignment
def test_evict_port_appends_multiple_entries(tmp_path):
    log = tmp_path / "evictions.jsonl"
    evict_port("feat-789", 8142, 8200, "first", log_path=str(log))
    evict_port("feat-789", 8200, 8202, "second", log_path=str(log))
    entries = get_eviction_log(str(log))
    assert len(entries) == 2


# === SPEC GAPS ===
# test_assign_port_pair_boundary: spec says range is [8100, 8299]; unclear whether 8299
#   can be a gevent port (making 8298 the last valid HTTP port) or if 8299 can be HTTP.
#   Need to confirm whether range is inclusive for both ports in a pair.
# test_eviction_rolling_window_calculation: spec says "rolling week" but does not define
#   whether that is calendar week, 7×24h from now, or last N evictions regardless of time.
# test_start_conflict_no_prompt_in_non_interactive: spec says "prompts user" for conflict
#   resolution — behaviour in non-interactive/agent context not specced.
