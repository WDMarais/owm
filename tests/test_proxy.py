"""
Tests for the proxy backends (nginx block generation + reload wiring).
Covers: Worktrees and branch ownership / proxy section.
"""
import pytest
from unittest.mock import patch, MagicMock

from owm.proxy import (
    NginxBackend, get_proxy_backend, _nginx_reload, _nginx_config_includes,
)
from owm.config import ProxyConfig


# ---------------------------------------------------------------------------
# Block generation + location (_proxy/<name>.nginx.conf, to match init's stub
# glob `include _proxy/*.nginx.conf`)
# ---------------------------------------------------------------------------

@pytest.mark.proxy
def test_nginx_block_written_to_proxy_dir_with_nginx_conf_suffix(tmp_path):
    NginxBackend().write_instance("pd-496", 8108, 8109, "localhost", str(tmp_path))
    block_path = tmp_path / "_proxy" / "pd-496.nginx.conf"
    assert block_path.is_file()
    block = block_path.read_text()
    assert "server_name pd-496.localhost;" in block
    assert "listen 80;" in block
    assert "upstream pd_496 { server 127.0.0.1:8108; }" in block
    assert "upstream pd_496_lp { server 127.0.0.1:8109; }" in block
    assert "proxy_pass http://pd_496;" in block


@pytest.mark.proxy
def test_nginx_block_suffix_matches_init_stub_glob(tmp_path):
    """The init stub includes _proxy/*.nginx.conf — a plain .conf would never load."""
    NginxBackend().write_instance("feat-1", 8100, 8101, "localhost", str(tmp_path))
    assert (tmp_path / "_proxy" / "feat-1.nginx.conf").is_file()
    assert not (tmp_path / "_proxy" / "feat-1.conf").exists()


@pytest.mark.proxy
def test_nginx_write_creates_proxy_dir(tmp_path):
    NginxBackend().write_instance("feat-1", 8100, 8101, "localhost", str(tmp_path))
    assert (tmp_path / "_proxy").is_dir()


@pytest.mark.proxy
def test_nginx_write_reloads(tmp_path):
    with patch("owm.proxy._nginx_reload") as reload:
        NginxBackend().write_instance("feat-1", 8100, 8101, "localhost", str(tmp_path))
    reload.assert_called_once()


@pytest.mark.proxy
def test_nginx_remove_deletes_block_and_reloads(tmp_path):
    backend = NginxBackend()
    backend.write_instance("feat-1", 8100, 8101, "localhost", str(tmp_path))
    assert (tmp_path / "_proxy" / "feat-1.nginx.conf").is_file()

    with patch("owm.proxy._nginx_reload") as reload:
        backend.remove_instance("feat-1", str(tmp_path))
    assert not (tmp_path / "_proxy" / "feat-1.nginx.conf").exists()
    reload.assert_called_once()


@pytest.mark.proxy
def test_nginx_remove_missing_block_is_noop_but_still_reloads(tmp_path):
    with patch("owm.proxy._nginx_reload") as reload:
        NginxBackend().remove_instance("ghost", str(tmp_path))
    reload.assert_called_once()


# ---------------------------------------------------------------------------
# Reload command construction (best-effort)
# ---------------------------------------------------------------------------

@pytest.mark.proxy
def test_nginx_reload_runs_sudo_reload():
    # _nginx_reload imported by name above binds the real function, so the autouse
    # stub (which patches owm.proxy._nginx_reload) does not shadow this call.
    with patch("owm.proxy.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0)
        ok = _nginx_reload()
    run.assert_called_once_with(
        ["sudo", "nginx", "-s", "reload"], check=False, capture_output=True, text=True,
    )
    assert ok is True


@pytest.mark.proxy
def test_nginx_reload_nonzero_returns_false():
    with patch("owm.proxy.subprocess.run") as run:
        run.return_value = MagicMock(returncode=1)
        assert _nginx_reload() is False


@pytest.mark.proxy
def test_nginx_reload_missing_binary_is_best_effort():
    with patch("owm.proxy.subprocess.run", side_effect=FileNotFoundError):
        assert _nginx_reload() is False


# ---------------------------------------------------------------------------
# Warnings: a written block that nginx won't serve (reload didn't apply, or the
# _proxy dir isn't included) must not look like success.
# ---------------------------------------------------------------------------

@pytest.mark.proxy
def test_nginx_write_warns_when_reload_does_not_apply(tmp_path, capsys):
    with patch("owm.proxy._nginx_reload", return_value=False):
        NginxBackend().write_instance("feat-1", 8100, 8101, "localhost", str(tmp_path))
    err = capsys.readouterr().err
    assert "did not apply" in err
    assert "feat-1.localhost" in err


@pytest.mark.proxy
def test_nginx_write_warns_when_proxy_dir_not_included(tmp_path, capsys):
    with patch("owm.proxy._nginx_reload", return_value=True), \
         patch("owm.proxy._nginx_config_includes", return_value=False):
        NginxBackend().write_instance("feat-1", 8100, 8101, "localhost", str(tmp_path))
    err = capsys.readouterr().err
    assert "no nginx `include`" in err
    assert "feat-1.localhost" in err


@pytest.mark.proxy
def test_nginx_write_silent_when_reloaded_and_included(tmp_path, capsys):
    with patch("owm.proxy._nginx_reload", return_value=True), \
         patch("owm.proxy._nginx_config_includes", return_value=True):
        NginxBackend().write_instance("feat-1", 8100, 8101, "localhost", str(tmp_path))
    assert capsys.readouterr().err == ""


@pytest.mark.proxy
def test_nginx_config_includes_finds_include_of_proxy_dir(tmp_path):
    proxy_dir = tmp_path / "ws" / "_proxy"
    proxy_dir.mkdir(parents=True)
    conf_d = tmp_path / "etc" / "conf.d"
    conf_d.mkdir(parents=True)
    (conf_d / "owm-ws.conf").write_text(f"include {proxy_dir}/*.nginx.conf;\n")
    assert _nginx_config_includes(str(proxy_dir), roots=(str(conf_d),)) is True


@pytest.mark.proxy
def test_nginx_config_includes_false_when_readable_but_absent(tmp_path):
    proxy_dir = tmp_path / "ws" / "_proxy"
    proxy_dir.mkdir(parents=True)
    conf_d = tmp_path / "etc" / "conf.d"
    conf_d.mkdir(parents=True)
    (conf_d / "other.conf").write_text("include /some/other/path/*.conf;\n")
    assert _nginx_config_includes(str(proxy_dir), roots=(str(conf_d),)) is False


@pytest.mark.proxy
def test_nginx_config_includes_true_when_no_config_readable(tmp_path):
    # Nothing to read → can't tell → don't cry wolf.
    proxy_dir = tmp_path / "ws" / "_proxy"
    proxy_dir.mkdir(parents=True)
    assert _nginx_config_includes(str(proxy_dir), roots=(str(tmp_path / "nope"),)) is True


# ---------------------------------------------------------------------------
# Removal goes through the backend (location-agnostic, idempotent)
# ---------------------------------------------------------------------------

@pytest.mark.proxy
def test_remove_proxy_block_removes_nginx_block(tmp_path):
    """Regression: _remove_proxy_block must delegate to the backend, not gate on a
    stale path — otherwise archive/delete leaves the block routing to a dead instance."""
    from owm.archive import _remove_proxy_block

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "workspace.toml").write_text(
        "[repos]\n[clusters]\n[proxy]\nbackend = \"nginx\"\ndomain_suffix = \"localhost\"\n"
    )
    get_proxy_backend(ProxyConfig(domain_suffix="localhost", backend="nginx")) \
        .write_instance("feat-1", 8100, 8101, "localhost", str(ws))
    assert (ws / "_proxy" / "feat-1.nginx.conf").is_file()

    removed = _remove_proxy_block("feat-1", str(ws))
    assert removed is True
    assert not (ws / "_proxy" / "feat-1.nginx.conf").exists()
