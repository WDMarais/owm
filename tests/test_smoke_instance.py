"""
Smoke tests for instance.py filesystem operations.
No mocks — tests exercise real disk I/O.

generate_instance_conf: verifies the INI string is parseable by configparser,
not just a string-match on known substrings.

new_instance: verifies the toml file is written to the correct location and
is parseable by parse_instance_config (catches malformed toml silently
produced by f-string templates).
"""
import configparser
import pytest

from owm.instance import new_instance, generate_instance_conf
from owm.config import parse_instance_config
from owm.errors import OwmError


# ---------------------------------------------------------------------------
# generate_instance_conf — real INI parse
# ---------------------------------------------------------------------------

@pytest.mark.smoke
def test_smoke_generate_instance_conf_parses_as_ini():
    conf = generate_instance_conf("feat-789", http_port=8142, gevent_port=8143, workers=2)
    parser = configparser.ConfigParser()
    parser.read_string(conf)
    assert parser.has_section("options")
    assert parser.getint("options", "http_port") == 8142
    assert parser.getint("options", "gevent_port") == 8143
    assert parser.getint("options", "workers") == 2


@pytest.mark.smoke
def test_smoke_generate_instance_conf_dbfilter_present_when_proxy_active():
    conf = generate_instance_conf("feat-789", http_port=8142, gevent_port=8143, workers=2,
                                  proxy_active=True)
    parser = configparser.ConfigParser()
    parser.read_string(conf)
    assert parser.get("options", "dbfilter") == "^feat-789$"


@pytest.mark.smoke
def test_smoke_generate_instance_conf_no_dbfilter_when_proxy_inactive():
    conf = generate_instance_conf("feat-789", http_port=8142, gevent_port=8143, workers=2,
                                  proxy_active=False)
    parser = configparser.ConfigParser()
    parser.read_string(conf)
    assert not parser.has_option("options", "dbfilter")


@pytest.mark.smoke
def test_smoke_generate_instance_conf_documents_addons_order():
    """The generated conf carries the first-path-wins precedence note immediately above
    addons_path, and stays INI-parseable (comment, not a key)."""
    conf = generate_instance_conf("feat-789", http_port=8142, gevent_port=8143, workers=2,
                                  addons_path=["/ws/instances/feat-789/customer-config",
                                               "/ws/_shared/odoo/19.0/addons"])
    lines = conf.splitlines()
    addons_idx = next(i for i, l in enumerate(lines) if l.startswith("addons_path ="))
    preceding = "\n".join(lines[:addons_idx])
    assert "first path wins" in preceding
    assert "repo_priority" in preceding
    # still valid INI — the note is a comment
    parser = configparser.ConfigParser()
    parser.read_string(conf)
    assert parser.get("options", "addons_path").startswith("/ws/instances/feat-789/customer-config")


# ---------------------------------------------------------------------------
# new_instance — disk write + round-trip parse
# ---------------------------------------------------------------------------

@pytest.mark.smoke
def test_smoke_new_instance_writes_toml_file(tmp_path):
    result = new_instance(
        name="feat-789",
        repos={"odoo_like": "main:shared", "product_core": "feat-789-dev:main"},
        workspace_root=str(tmp_path),
    )
    toml_path = tmp_path / "instances" / "feat-789" / "instance.toml"
    assert toml_path.exists()
    assert result.toml_path == str(toml_path)


@pytest.mark.smoke
def test_smoke_new_instance_toml_round_trips_through_parser(tmp_path):
    """Written instance.toml must parse without errors — catches f-string template bugs."""
    new_instance(
        name="feat-789",
        repos={"odoo_like": "main:shared", "product_core": "feat-789-dev:main"},
        workspace_root=str(tmp_path),
    )
    toml_path = tmp_path / "instances" / "feat-789" / "instance.toml"
    conf = parse_instance_config(toml_path.read_text())
    assert conf.database.name == "feat-789"
    assert conf.server.http_port > 0


@pytest.mark.smoke
def test_smoke_new_instance_already_exists_raises(tmp_path):
    new_instance(
        name="feat-789",
        repos={"odoo_like": "main:shared"},
        workspace_root=str(tmp_path),
    )
    with pytest.raises(OwmError) as exc_info:
        new_instance(
            name="feat-789",
            repos={"odoo_like": "main:shared"},
            workspace_root=str(tmp_path),
        )
    assert "ALREADY_EXISTS" in str(exc_info.value)
