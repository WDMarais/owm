"""
Tests for instance start, stop, kill, restart, and health checks.
Covers: Instance lifecycle — start/stop section.
"""
import pytest
from unittest.mock import patch, MagicMock

from owm.errors import OwmError, START_TIMEOUT
from owm.instance import start_instance, stop_instance, kill_instance
from owm.instance import restart_instance, health_check
from owm.instance import _pid_file_path, _write_pid, _read_pid, _process_alive


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
http_port = 8142
gevent_port = 8143
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
def test_pid_file_round_trip(tmp_path):
    inst_dir = tmp_path / "instances" / "feat-789"
    inst_dir.mkdir(parents=True)
    _write_pid("feat-789", str(tmp_path), 1234)
    assert _read_pid("feat-789", str(tmp_path)) == 1234


@pytest.mark.instance_lifecycle_start_stop
def test_read_pid_returns_none_when_missing(tmp_path):
    inst_dir = tmp_path / "instances" / "feat-789"
    inst_dir.mkdir(parents=True)
    assert _read_pid("feat-789", str(tmp_path)) is None


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
               side_effect=OwmError("timed out waiting for instance to start (port 8142)", code=START_TIMEOUT)):
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
def test_stop_sends_signal_and_returns_immediately():
    result = stop_instance(instance="feat-789", wait=False)  # TODO: wire up
    assert result.status == "stopping"
    assert result.pid is not None


@pytest.mark.instance_lifecycle_start_stop
def test_stop_emits_stopped_event_when_process_exits():
    result = stop_instance(instance="feat-789", wait=True, simulate_clean_exit=True)  # TODO: wire up
    assert "instance_stopped" in result.events_emitted


@pytest.mark.instance_lifecycle_start_stop
def test_stop_wait_blocks_until_exit():
    result = stop_instance(instance="feat-789", wait=True, simulate_clean_exit=True)  # TODO: wire up
    assert result.status == "stopped"


@pytest.mark.instance_lifecycle_start_stop
def test_stop_not_running_is_noop():
    result = stop_instance(instance="feat-789", running=False)  # TODO: wire up
    assert result.status == "not_running"


@pytest.mark.instance_lifecycle_start_stop
def test_stop_not_running_message_is_clear():
    result = stop_instance(instance="feat-789", running=False)  # TODO: wire up
    assert result.message is not None


# ---------------------------------------------------------------------------
# kill
# ---------------------------------------------------------------------------

@pytest.mark.instance_lifecycle_start_stop
def test_kill_running_instance():
    result = kill_instance(instance="feat-789", running=True, pid=1234)  # TODO: wire up
    assert result.status == "killed"
    assert result.pid == 1234


@pytest.mark.instance_lifecycle_start_stop
def test_kill_not_running_is_noop():
    result = kill_instance(instance="feat-789", running=False)  # TODO: wire up
    assert result.status == "not_running"


@pytest.mark.instance_lifecycle_start_stop
def test_stop_never_auto_kills():
    """Stop timeout must not implicitly kill — owm_kill is always explicit."""
    result = stop_instance(instance="feat-789", wait=True, simulate_clean_exit=False, timeout_seconds=1)  # TODO: wire up
    assert result.status in ("timeout", "stop_timeout")
    assert result.force_killed is False
    assert "kill" in result.hint.lower()  # hint tells user to call kill explicitly


# ---------------------------------------------------------------------------
# restart
# ---------------------------------------------------------------------------

@pytest.mark.instance_lifecycle_start_stop
def test_restart_stops_and_starts_returning_new_pid():
    result = restart_instance(
        instance="feat-789",
        wait=False,
        simulate_stop_clean=True,
        new_pid=1235,
    )  # TODO: wire up
    assert result.status == "restarted"
    assert result.pid == 1235
    assert result.url == "https://feat-789.localhost"


@pytest.mark.instance_lifecycle_start_stop
def test_restart_stop_timeout_returns_error_without_killing():
    """Restart stop timeout → error, no implicit kill."""
    with pytest.raises(Exception) as exc_info:
        restart_instance(
            instance="feat-789",
            simulate_stop_clean=False,
            timeout_seconds=1,
        )  # TODO: wire up
    err = str(exc_info.value)
    assert "STOP_TIMEOUT" in err or "stop timed out" in err.lower()
    assert "kill" in err.lower()  # hint to call owm_kill


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------

@pytest.mark.instance_lifecycle_start_stop
def test_health_running_and_http_alive():
    result = health_check(instance="feat-789", pid=1234, http_alive=True)  # TODO: wire up
    assert result == {"status": "healthy", "pid": 1234, "http_alive": True, "url": "https://feat-789.localhost"}


@pytest.mark.instance_lifecycle_start_stop
def test_health_starting():
    result = health_check(instance="feat-789", pid=1234, http_alive=False, process_running=True)  # TODO: wire up
    assert result["status"] == "starting"
    assert result["http_alive"] is False


@pytest.mark.instance_lifecycle_start_stop
def test_health_unhealthy_process_running_no_http():
    result = health_check(instance="feat-789", pid=1234, http_alive=False, process_running=True, timed_out=True)  # TODO: wire up
    assert result["status"] == "unhealthy"


@pytest.mark.instance_lifecycle_start_stop
def test_health_stopped():
    result = health_check(instance="feat-789", pid=None, process_running=False)  # TODO: wire up
    assert result == {"status": "stopped"}


@pytest.mark.instance_lifecycle_start_stop
def test_health_unmanaged_process():
    """Process on instance port but not started by owm → status: unmanaged."""
    result = health_check(instance="feat-789", pid=9999, unmanaged=True, port=8142)  # TODO: wire up
    assert result["status"] == "unmanaged"
    assert result["pid"] == 9999
    assert result["port"] == 8142


@pytest.mark.instance_lifecycle_start_stop
def test_health_is_process_and_http_only_not_db_or_venv():
    """Health check scope: process + HTTP only; DB/venv/module state is owm_validate."""
    result = health_check(instance="feat-789", pid=1234, http_alive=True)  # TODO: wire up
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
