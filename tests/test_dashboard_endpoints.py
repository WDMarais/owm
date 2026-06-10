"""
Coverage for the dashboard server's git-action endpoints (sync / push / pull-base).

These endpoints call the owm lib functions in-process (sync_worktrees,
push_worktree, pull_base_instance) rather than shelling out. We patch the lib
boundary and drive the FastAPI app through Starlette's TestClient, exercising
real HTTP routing and serialization without real git or a live remote.

Contract under test — what dashboard/app.js relies on:
  - on success the endpoint returns the lib result dict (no `error` key)
  - an OwmError becomes a 200 response with {"error": str(e), "code": e.code}
    (the error-toast path); the handler does not raise / 500

Out of scope here: the front-end button-state logic (which sync state shows
Sync / Push / Pull Base) lives in app.js `_syncSummary`; covering it needs a JS
test harness, which is a separate call.
"""
import os
from pathlib import Path
from unittest.mock import patch

import pytest

# server.py resolves WORKSPACE at import time; point it at the committed fixture
# workspace (a valid workspace.toml tree) so the import succeeds. The value is
# irrelevant to these tests beyond that — the lib calls are patched.
_FIXTURE_WORKSPACE = Path(__file__).parent.parent / "test_fixtures" / "workspace"
os.environ.setdefault("OWM_WORKSPACE", str(_FIXTURE_WORKSPACE))

from starlette.testclient import TestClient  # noqa: E402

from dashboard import server  # noqa: E402

pytestmark = pytest.mark.dashboard


@pytest.fixture
def client():
    return TestClient(server.app)


# ── sync ────────────────────────────────────────────────────────────────────

def test_sync_calls_lib_in_process(client):
    """Sync runs against the lib directly, not the owm subprocess."""
    with patch("dashboard.server.sync_worktrees",
               return_value={"repos": {"customer-config": {"status": "fast-forwarded"}}}) as mock_sync:
        resp = client.post("/api/instance/feat-789/sync/customer-config")

    assert resp.status_code == 200
    assert resp.json() == {"repos": {"customer-config": {"status": "fast-forwarded"}}}
    mock_sync.assert_called_once_with("feat-789", str(server.WORKSPACE), repo="customer-config")


def test_sync_owm_error_is_shaped(client):
    """An OwmError from the lib becomes the dashboard's {error, code} body."""
    from owm.errors import OwmError, DIRTY_WORKTREE
    with patch("dashboard.server.sync_worktrees",
               side_effect=OwmError("customer-config has uncommitted changes", code=DIRTY_WORKTREE)):
        resp = client.post("/api/instance/feat-789/sync/customer-config")

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "DIRTY_WORKTREE"
    assert "uncommitted changes" in body["error"]


# ── push ────────────────────────────────────────────────────────────────────

def test_push_calls_lib_in_process(client):
    """Push runs against the lib directly, not the owm subprocess."""
    with patch("dashboard.server.push_worktree",
               return_value={"status": "pushed", "repo": "customer-config", "branch": "feat-789-dev"}) as mock_push:
        resp = client.post("/api/instance/feat-789/push/customer-config")

    assert resp.status_code == 200
    assert resp.json()["status"] == "pushed"
    mock_push.assert_called_once_with("feat-789", str(server.WORKSPACE), repo="customer-config")


def test_push_owm_error_is_shaped(client):
    """An OwmError from the lib (e.g. a shared repo) becomes {error, code}."""
    from owm.errors import OwmError, SHARED_REPO
    with patch("dashboard.server.push_worktree",
               side_effect=OwmError("odoo_like is a shared repo", code=SHARED_REPO)):
        resp = client.post("/api/instance/feat-789/push/odoo_like")

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "SHARED_REPO"
    assert "shared repo" in body["error"]


# ── pull-base ───────────────────────────────────────────────────────────────

def test_pull_base_calls_lib_in_process(client):
    """Pull-base runs against the lib directly, not the owm subprocess."""
    with patch("dashboard.server.pull_base_instance",
               return_value={"results": {"customer-config": {"status": "merged", "base": "dev"}}}) as mock_pb:
        resp = client.post("/api/instance/feat-789/pull-base/customer-config")

    assert resp.status_code == 200
    assert resp.json() == {"results": {"customer-config": {"status": "merged", "base": "dev"}}}
    mock_pb.assert_called_once_with("feat-789", str(server.WORKSPACE), repo="customer-config")


def test_pull_base_owm_error_is_shaped(client):
    """A dirty-worktree pre-flight OwmError becomes {error, code}."""
    from owm.errors import OwmError, DIRTY_WORKTREE
    with patch("dashboard.server.pull_base_instance",
               side_effect=OwmError("customer-config has uncommitted changes", code=DIRTY_WORKTREE)):
        resp = client.post("/api/instance/feat-789/pull-base/customer-config")

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "DIRTY_WORKTREE"
    assert "uncommitted changes" in body["error"]


# ── processes ─────────────────────────────────────────────────────────────────

def test_processes_serves_the_four_odoo_ps_tiers(client):
    """/api/processes composes from odoo_ps() and maps each tier onto the field
    names app.js's row renderers read. Patches the classifier so the assertion is
    about the endpoint's shaping, not host process state.

    Contract under test — what dashboard/app.js relies on:
      - top-level tiers are managed/orphaned/foreign/squatters (the dead
        `unregistered` section is gone)
      - orphaned rows carry {name, pid, ports}      (_orphanedRow)
      - foreign rows carry  {cmd, pid, ports}       (_foreignRow)
      - squatter rows carry {cmd, pid, ports} with the instance and port in cmd
        (_squatterRow); squatters are already classifier-filtered upstream
    """
    fake = {
        "managed":   [{"instance": "feat-789", "pid": 1, "port": 8069, "url": "u", "state": "running"}],
        "orphaned":  [{"pid": 222, "instance": "old-feat"}],
        "foreign":   [{"pid": 333, "cmdline": "/opt/odoo/odoo-bin --config /etc/odoo/odoo.conf"}],
        "squatters": [{"instance": "pd-479", "http_port": 8102, "pid": 444}],
    }
    with patch("dashboard.server.odoo_ps", return_value=fake):
        resp = client.get("/api/processes")

    assert resp.status_code == 200
    data = resp.json()
    assert set(data) == {"managed", "orphaned", "foreign", "squatters"}
    assert "unregistered" not in data

    assert data["orphaned"] == [{"name": "old-feat", "pid": 222, "ports": []}]
    assert data["foreign"] == [
        {"cmd": "/opt/odoo/odoo-bin --config /etc/odoo/odoo.conf", "pid": 333, "ports": []}
    ]
    assert data["squatters"] == [{"cmd": "pd-479 (:8102)", "pid": 444, "ports": [8102]}]


# ── missing instance ────────────────────────────────────────────────────────

def test_action_on_missing_instance_is_not_found(client):
    """A missing instance yields a shaped NOT_FOUND, not a 500.

    Drives the real sync_worktrees (unmocked) against the fixture workspace,
    where 'ghost-instance' does not exist — the lib raises NOT_FOUND rather than
    leaking FileNotFoundError, and the endpoint shapes it.
    """
    resp = client.post("/api/instance/ghost-instance/sync/foo")

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "NOT_FOUND"
