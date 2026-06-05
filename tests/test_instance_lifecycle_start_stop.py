"""
Tests for instance start, stop, kill, restart, and health checks.
Covers: Instance lifecycle — start/stop section.
"""
import json
import signal
import pytest
from unittest.mock import patch, MagicMock

from owm.errors import OwmError, START_TIMEOUT
from owm.instance import start_instance, stop_instance, kill_instance
from owm.instance import restart_instance, health_check
from owm.instance import StartResult, StopResult
from owm.instance import (
    _state_file_path,
    _write_pid,
    _read_pid,
    _clear_pid,
    _process_alive,
)
from owm.instance import _PID_UNSET


# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------

_INSTANCE_TOML = """\
[repos]
odoo_like = "main:shared"

[database]
name = "owm_test_feat789"
pg_port = 5432

[server]
http_port = 18142
gevent_port = 18143
workers = 2
"""


def _make_instance_dir(tmp_path, instance="feat-789"):
    inst_dir = tmp_path / "instances" / instance
    inst_dir.mkdir(parents=True)
    (inst_dir / "instance.toml").write_text(_INSTANCE_TOML)
    return inst_dir


# ---------------------------------------------------------------------------
# PID file helpers
# ---------------------------------------------------------------------------

@pytest.mark.instance_lifecycle_start_stop
def test_state_pid_round_trip(tmp_path):
    inst_dir = tmp_path / "instances" / "feat-789"
    inst_dir.mkdir(parents=True)
    _write_pid("feat-789", str(tmp_path), 1234)
    assert _read_pid("feat-789", str(tmp_path)) == 1234


@pytest.mark.instance_lifecycle_start_stop
def test_read_pid_returns_none_when_state_absent(tmp_path):
    inst_dir = tmp_path / "instances" / "feat-789"
    inst_dir.mkdir(parents=True)
    assert _read_pid("feat-789", str(tmp_path)) is None


@pytest.mark.instance_lifecycle_start_stop
def test_state_pid_unset_sentinel_on_stop(tmp_path):
    inst_dir = tmp_path / "instances" / "feat-789"
    inst_dir.mkdir(parents=True)
    _write_pid("feat-789", str(tmp_path), 1234)
    _clear_pid("feat-789", str(tmp_path))
    state = json.loads(open(_state_file_path("feat-789", str(tmp_path))).read())
    assert state["pid"] == _PID_UNSET      # explicit sentinel, not null
    assert _read_pid("feat-789", str(tmp_path)) is None  # reads as "not running"


@pytest.mark.instance_lifecycle_start_stop
def test_process_alive_delegates_to_psutil():
    with patch("owm.instance.psutil.pid_exists", return_value=True):
        assert _process_alive(1234) is True
    with patch("owm.instance.psutil.pid_exists", return_value=False):
        assert _process_alive(9999999) is False


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------

@pytest.mark.instance_lifecycle_start_stop
def test_start_spawns_and_returns_pid_immediately(tmp_path):
    _make_instance_dir(tmp_path)
    mock_proc = MagicMock()
    mock_proc.pid = 1234
    with patch("owm.instance.subprocess.Popen", return_value=mock_proc), \
         patch("owm.instance._read_pid", return_value=None):
        result = start_instance("feat-789", str(tmp_path), wait=False)
    assert result.status == "spawned"
    assert result.pid is not None
    assert isinstance(result.pid, int)


@pytest.mark.instance_lifecycle_start_stop
def test_start_emits_starting_event(tmp_path):
    _make_instance_dir(tmp_path)
    mock_proc = MagicMock()
    mock_proc.pid = 1234
    with patch("owm.instance.subprocess.Popen", return_value=mock_proc), \
         patch("owm.instance._read_pid", return_value=None):
        result = start_instance("feat-789", str(tmp_path), wait=False)
    assert "instance_starting" in result.events_emitted


@pytest.mark.instance_lifecycle_start_stop
def test_start_wait_blocks_until_healthy(tmp_path):
    _make_instance_dir(tmp_path)
    mock_proc = MagicMock()
    mock_proc.pid = 1234
    with patch("owm.instance.subprocess.Popen", return_value=mock_proc), \
         patch("owm.instance._read_pid", return_value=None), \
         patch("owm.instance._wait_for_http"):
        result = start_instance("feat-789", str(tmp_path), wait=True)
    assert result.status == "healthy"
    assert result.pid is not None


@pytest.mark.instance_lifecycle_start_stop
def test_start_wait_emits_healthy_event_on_success(tmp_path):
    _make_instance_dir(tmp_path)
    mock_proc = MagicMock()
    mock_proc.pid = 1234
    with patch("owm.instance.subprocess.Popen", return_value=mock_proc), \
         patch("owm.instance._read_pid", return_value=None), \
         patch("owm.instance._wait_for_http"):
        result = start_instance("feat-789", str(tmp_path), wait=True)
    assert "instance_healthy" in result.events_emitted


@pytest.mark.instance_lifecycle_start_stop
def test_start_wait_timeout_exits_nonzero(tmp_path):
    _make_instance_dir(tmp_path)
    mock_proc = MagicMock()
    mock_proc.pid = 1234
    with patch("owm.instance.subprocess.Popen", return_value=mock_proc), \
         patch("owm.instance._read_pid", return_value=None), \
         patch("owm.instance._wait_for_http",
               side_effect=OwmError("timed out waiting for instance to start (port 18142)", code=START_TIMEOUT)):
        with pytest.raises(Exception) as exc_info:
            start_instance("feat-789", str(tmp_path), wait=True, timeout_seconds=1)
    assert "START_TIMEOUT" in str(exc_info.value) or "timed out" in str(exc_info.value).lower()


@pytest.mark.instance_lifecycle_start_stop
def test_start_already_running_is_noop(tmp_path):
    _make_instance_dir(tmp_path)
    with patch("owm.instance._read_pid", return_value=9999), \
         patch("owm.instance._process_alive", return_value=True):
        result = start_instance("feat-789", str(tmp_path))
    assert result.status == "already_running"
    assert result.pid is not None


@pytest.mark.instance_lifecycle_start_stop
def test_start_already_running_message_is_clear(tmp_path):
    _make_instance_dir(tmp_path)
    with patch("owm.instance._read_pid", return_value=9999), \
         patch("owm.instance._process_alive", return_value=True):
        result = start_instance("feat-789", str(tmp_path))
    assert "already running" in result.message.lower() or "feat-789" in result.message


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------

@pytest.mark.instance_lifecycle_start_stop
def test_stop_sends_signal_and_returns_immediately(tmp_path):
    _make_instance_dir(tmp_path)
    with patch("owm.instance._read_pid", return_value=1234), \
         patch("owm.instance._process_alive", return_value=True), \
         patch("owm.instance.os.kill") as mock_kill:
        result = stop_instance("feat-789", str(tmp_path), wait=False)
    mock_kill.assert_called_once_with(1234, signal.SIGTERM)
    assert result.status == "stopping"
    assert result.pid is not None


@pytest.mark.instance_lifecycle_start_stop
def test_stop_emits_stopped_event_when_process_exits(tmp_path):
    _make_instance_dir(tmp_path)
    with patch("owm.instance._read_pid", return_value=1234), \
         patch("owm.instance._process_alive", return_value=True), \
         patch("owm.instance.os.kill"), \
         patch("owm.instance._wait_for_stop", return_value=True), \
         patch("owm.instance._clear_pid"):
        result = stop_instance("feat-789", str(tmp_path), wait=True)
    assert "instance_stopped" in result.events_emitted


@pytest.mark.instance_lifecycle_start_stop
def test_stop_wait_blocks_until_exit(tmp_path):
    _make_instance_dir(tmp_path)
    with patch("owm.instance._read_pid", return_value=1234), \
         patch("owm.instance._process_alive", return_value=True), \
         patch("owm.instance.os.kill"), \
         patch("owm.instance._wait_for_stop", return_value=True), \
         patch("owm.instance._clear_pid"):
        result = stop_instance("feat-789", str(tmp_path), wait=True)
    assert result.status == "stopped"


@pytest.mark.instance_lifecycle_start_stop
def test_stop_not_running_is_noop(tmp_path):
    _make_instance_dir(tmp_path)
    with patch("owm.instance._read_pid", return_value=None):
        result = stop_instance("feat-789", str(tmp_path))
    assert result.status == "not_running"


@pytest.mark.instance_lifecycle_start_stop
def test_stop_not_running_message_is_clear(tmp_path):
    _make_instance_dir(tmp_path)
    with patch("owm.instance._read_pid", return_value=None):
        result = stop_instance("feat-789", str(tmp_path))
    assert result.message is not None


# ---------------------------------------------------------------------------
# kill
# ---------------------------------------------------------------------------

@pytest.mark.instance_lifecycle_start_stop
def test_kill_running_instance(tmp_path):
    _make_instance_dir(tmp_path)
    with patch("owm.instance._read_pid", return_value=1234), \
         patch("owm.instance._process_alive", return_value=True), \
         patch("owm.instance.os.kill"), \
         patch("owm.instance._clear_pid"):
        result = kill_instance("feat-789", str(tmp_path))
    assert result.status == "killed"
    assert result.pid == 1234


@pytest.mark.instance_lifecycle_start_stop
def test_kill_not_running_is_noop(tmp_path):
    _make_instance_dir(tmp_path)
    with patch("owm.instance._read_pid", return_value=None):
        result = kill_instance("feat-789", str(tmp_path))
    assert result.status == "not_running"


@pytest.mark.instance_lifecycle_start_stop
def test_stop_never_auto_kills(tmp_path):
    """Stop timeout must not implicitly kill — owm_kill is always explicit."""
    _make_instance_dir(tmp_path)
    with patch("owm.instance._read_pid", return_value=1234), \
         patch("owm.instance._process_alive", return_value=True), \
         patch("owm.instance.os.kill"), \
         patch("owm.instance._wait_for_stop", return_value=False):
        result = stop_instance("feat-789", str(tmp_path), wait=True, timeout_seconds=1)
    assert result.status in ("timeout", "stop_timeout")
    assert result.force_killed is False
    assert "kill" in result.hint.lower()


# ---------------------------------------------------------------------------
# restart
# ---------------------------------------------------------------------------

@pytest.mark.instance_lifecycle_start_stop
def test_restart_stops_and_starts_returning_new_pid(tmp_path):
    _make_instance_dir(tmp_path)
    mock_stop = StopResult(status="stopped", pid=1234)
    mock_start = StartResult(status="spawned", pid=1235)
    with patch("owm.instance.stop_instance", return_value=mock_stop), \
         patch("owm.instance.start_instance", return_value=mock_start):
        result = restart_instance("feat-789", str(tmp_path), wait=False)
    assert result.status == "restarted"
    assert result.pid == 1235
    assert result.url == "https://feat-789.localhost"


@pytest.mark.instance_lifecycle_start_stop
def test_restart_stop_timeout_returns_error_without_killing(tmp_path):
    """Restart stop timeout → error, no implicit kill."""
    _make_instance_dir(tmp_path)
    mock_stop = StopResult(status="stop_timeout", force_killed=False, hint="run owm kill to force-stop the instance")
    with patch("owm.instance.stop_instance", return_value=mock_stop):
        with pytest.raises(Exception) as exc_info:
            restart_instance("feat-789", str(tmp_path), timeout_seconds=1)
    err = str(exc_info.value)
    assert "STOP_TIMEOUT" in err or "stop timed out" in err.lower()
    assert "kill" in err.lower()


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------

@pytest.mark.instance_lifecycle_start_stop
def test_health_running_and_http_alive(tmp_path):
    _make_instance_dir(tmp_path)
    with patch("owm.instance._read_pid", return_value=1234), \
         patch("owm.instance._process_alive", return_value=True), \
         patch("owm.instance._probe_http", return_value=True):
        result = health_check("feat-789", str(tmp_path))
    assert result == {"status": "healthy", "pid": 1234, "http_alive": True, "url": "https://feat-789.localhost"}


@pytest.mark.instance_lifecycle_start_stop
def test_health_starting(tmp_path):
    _make_instance_dir(tmp_path)
    with patch("owm.instance._read_pid", return_value=1234), \
         patch("owm.instance._process_alive", return_value=True), \
         patch("owm.instance._probe_http", return_value=False):
        result = health_check("feat-789", str(tmp_path))  # wait=False by default
    assert result["status"] == "starting"
    assert result["http_alive"] is False


@pytest.mark.instance_lifecycle_start_stop
def test_health_unhealthy_process_running_no_http(tmp_path):
    _make_instance_dir(tmp_path)
    with patch("owm.instance._read_pid", return_value=1234), \
         patch("owm.instance._process_alive", return_value=True), \
         patch("owm.instance._probe_http", return_value=False), \
         patch("owm.instance._wait_for_http", side_effect=OwmError("timeout", code=START_TIMEOUT)):
        result = health_check("feat-789", str(tmp_path), wait=True)
    assert result["status"] == "unhealthy"


@pytest.mark.instance_lifecycle_start_stop
def test_health_stopped(tmp_path):
    _make_instance_dir(tmp_path)
    with patch("owm.instance._read_pid", return_value=None), \
         patch("owm.instance.find_conflicting_process", return_value=None):
        result = health_check("feat-789", str(tmp_path))
    assert result == {"status": "stopped"}


@pytest.mark.instance_lifecycle_start_stop
def test_health_unmanaged_process(tmp_path):
    """Process on instance port but not started by owm → status: unmanaged."""
    _make_instance_dir(tmp_path)
    with patch("owm.instance._read_pid", return_value=None), \
         patch("owm.instance.find_conflicting_process",
               return_value={"pid": 9999, "name": "nginx", "cmdline": "nginx -g daemon off;"}):
        result = health_check("feat-789", str(tmp_path))
    assert result["status"] == "unmanaged"
    assert result["pid"] == 9999
    assert result["port"] == 18142


@pytest.mark.instance_lifecycle_start_stop
def test_health_is_process_and_http_only_not_db_or_venv(tmp_path):
    """Health check scope: process + HTTP only; DB/venv/module state is owm_validate."""
    _make_instance_dir(tmp_path)
    with patch("owm.instance._read_pid", return_value=1234), \
         patch("owm.instance._process_alive", return_value=True), \
         patch("owm.instance._probe_http", return_value=True):
        result = health_check("feat-789", str(tmp_path))
    assert "db" not in result
    assert "venv" not in result
    assert "modules" not in result


# === SPEC GAPS ===
# test_start_venv_sync_triggered_on_requirements_change: spec says venv re-sync occurs
#   on owm start if stamp changed; timing relative to spawn is not specified (before or after?).
# test_start_module_install_triggered: spec says modules installed on start if missing;
#   whether this blocks spawn or runs asynchronously is not stated.
# test_health_url_scheme: spec implies https://feat-789.localhost; whether http:// is
#   returned during "starting" phase (before TLS proxy is active) is not specified.
