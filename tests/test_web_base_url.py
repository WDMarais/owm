"""
web.base.url pinning — re-owm sets an instance's web.base.url to its own
canonical address so Odoo stops advertising a port inherited from a cloned
template (the live bug: 13/16 dev instances stuck on the base's :8100).

URL derivation is a pure unit; the psql upsert is exercised through a patched
subprocess boundary (a real Odoo-initialised DB is too heavy for a unit suite —
the integration that proves it end-to-end against pg is a separate, heavier test).
"""
import subprocess
from unittest.mock import patch

import pytest

from owm.config import parse_workspace_config
from owm.instance import _instance_public_url, _set_web_base_url, pin_web_base_url

pytestmark = pytest.mark.web_base_url

_WS_NGINX = (
    '[repos]\nodoo_like = {path = "/dev/null", has_addons = true}\n'
    "[clusters]\n"
    '[proxy]\nbackend = "nginx"\ndomain_suffix = "dev.local"\n'
)
_WS_CADDY = (
    '[repos]\nodoo_like = {path = "/dev/null", has_addons = true}\n'
    "[clusters]\n"
    '[proxy]\nbackend = "caddy"\ndomain_suffix = "dev.local"\n'
)
_WS_NO_PROXY = (
    '[repos]\nodoo_like = {path = "/dev/null", has_addons = true}\n'
    "[clusters]\n"
)


# ── URL derivation ────────────────────────────────────────────────────────────

def test_web_base_url_is_http_subdomain_under_nginx():
    # nginx listens on :80 — the URL must be http, not https
    ws_conf = parse_workspace_config(_WS_NGINX)
    assert _instance_public_url("feat-789", 8142, ws_conf) == "http://feat-789.dev.local"


def test_web_base_url_is_https_subdomain_under_caddy():
    # Caddy serves tls internal — the URL must be https
    ws_conf = parse_workspace_config(_WS_CADDY)
    assert _instance_public_url("feat-789", 8142, ws_conf) == "https://feat-789.dev.local"


def test_web_base_url_falls_back_to_localhost_port_without_proxy():
    ws_conf = parse_workspace_config(_WS_NO_PROXY)
    assert _instance_public_url("feat-789", 8142, ws_conf) == "http://localhost:8142"


# ── psql upsert ───────────────────────────────────────────────────────────────

def test_set_web_base_url_upserts_value_and_keeps_freeze():
    with patch("owm.instance.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        ok = _set_web_base_url("owm_test_feat789", 5432, "https://feat-789.localhost")

    assert ok is True
    argv = run.call_args.args[0]
    assert argv[0] == "psql"
    assert "owm_test_feat789" in argv
    assert "5432" in argv
    sql = argv[-1]
    assert "web.base.url" in sql and "https://feat-789.localhost" in sql
    assert "web.base.url.freeze" in sql and "'True'" in sql
    assert "ON CONFLICT (key) DO UPDATE" in sql


def test_set_web_base_url_tolerant_of_uninitialised_db():
    """A fresh DB has no ir_config_parameter table — psql errors, and we report
    the no-op rather than raising, so the next start can pin it."""
    with patch("owm.instance.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 1, stdout="", stderr="relation does not exist")
        ok = _set_web_base_url("fresh_db", 5432, "https://x.localhost")

    assert ok is False


# ── orchestration (real config parse, patched pg) ─────────────────────────────

def test_pin_web_base_url_targets_the_proxy_subdomain(standard_instance_toml, tmp_workspace):
    """End-to-end through real instance + workspace config: tmp_workspace uses an
    nginx backend (domain_suffix=localhost), so the pinned URL is the http subdomain
    and the target DB is the instance's own."""
    with patch("owm.instance.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        pin_web_base_url("feat-789", str(tmp_workspace))

    sql = run.call_args.args[0][-1]
    assert "http://feat-789.localhost" in sql
    assert "owm_test_feat789" in " ".join(run.call_args.args[0])
