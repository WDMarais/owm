"""
Coverage for the dashboard server's git-action endpoints (sync / push / pull-base).

These endpoints were added without tests (commits 07705d2, eb94726). They shell
out to `owm` via subprocess; we mock that boundary and drive the FastAPI app
through Starlette's TestClient, so the tests exercise real HTTP routing and
serialization without a real `owm` binary, real git, or a live remote.

Contract under test — what dashboard/app.js relies on (it reads the JSON body and
toasts `_firstLine(output)` when `ok` is false):

  - each endpoint routes to the correct `owm` subcommand with `--repo <repo>`
  - the response body is {"ok": returncode == 0, "output": stdout + stderr}
  - a non-zero return code still returns HTTP 200 with ok=False and the combined
    output (the error-toast path) — the handler does not raise / 500

Out of scope here: the front-end button-state logic (which sync state shows
Sync / Push / Pull Base) lives in app.js `_syncSummary` and is documented there;
covering it needs a JS test harness, which is a separate call.
"""
import os
from pathlib import Path
from unittest.mock import patch

import pytest

# server.py resolves WORKSPACE at import time; point it at the committed fixture
# workspace (a valid workspace.toml tree) so the import succeeds. The value is
# irrelevant to these tests beyond that — subprocess is mocked.
_FIXTURE_WORKSPACE = Path(__file__).parent.parent / "test_fixtures" / "workspace"
os.environ.setdefault("OWM_WORKSPACE", str(_FIXTURE_WORKSPACE))

from starlette.testclient import TestClient  # noqa: E402

from dashboard import server  # noqa: E402

pytestmark = pytest.mark.dashboard


class _FakeCompleted:
    """Stand-in for subprocess.CompletedProcess."""

    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _FakeOwm:
    """Records subprocess.run calls and serves a programmable result."""

    def __init__(self):
        self.calls = []
        self.result = _FakeCompleted(0)

    def run(self, argv, **kwargs):
        self.calls.append({"argv": argv, "kwargs": kwargs})
        return self.result

    @property
    def last_argv(self):
        return self.calls[-1]["argv"]


@pytest.fixture
def fake_owm(monkeypatch):
    fake = _FakeOwm()
    monkeypatch.setattr(server.subprocess, "run", fake.run)
    return fake


@pytest.fixture
def client():
    return TestClient(server.app)


# (url action segment, expected owm subcommand)
ENDPOINTS = [
    ("push",      "push"),
    ("pull-base", "pull-base"),
]
_IDS = [subcommand for _, subcommand in ENDPOINTS]

# Realistic git failure output per action — the stderr a failing `owm` would
# surface, and what app.js renders the first line of into the error toast.
GIT_ERRORS = {
    "push": (
        "To bitbucket.org:acme/customer-config.git\n"
        " ! [rejected]        feat-789-dev -> feat-789-dev (non-fast-forward)\n"
        "error: failed to push some refs to 'origin'"
    ),
    "pull-base": (
        "fatal: Not possible to fast-forward, aborting.\n"
        "hint: diverged from origin/dev; resolve manually."
    ),
}


def _post(client, action, name="feat-789", repo="customer-config"):
    return client.post(f"/api/instance/{name}/{action}/{repo}")


@pytest.mark.parametrize("action, subcommand", ENDPOINTS, ids=_IDS)
def test_endpoint_routes_to_correct_owm_subcommand(client, fake_owm, action, subcommand):
    _post(client, action)

    assert len(fake_owm.calls) == 1
    argv = fake_owm.last_argv
    assert argv[0] == server._OWM_BIN
    assert argv[1] == subcommand
    assert "feat-789" in argv
    assert argv[-2:] == ["--repo", "customer-config"]


@pytest.mark.parametrize("action, subcommand", ENDPOINTS, ids=_IDS)
def test_endpoint_success_returns_ok_true_with_output(client, fake_owm, action, subcommand):
    fake_owm.result = _FakeCompleted(0, stdout="Everything up-to-date\n", stderr="")

    resp = _post(client, action)

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "output": "Everything up-to-date\n"}


@pytest.mark.parametrize("action, subcommand", ENDPOINTS, ids=_IDS)
def test_endpoint_failure_is_http_200_with_ok_false(client, fake_owm, action, subcommand):
    stderr = GIT_ERRORS[subcommand]
    fake_owm.result = _FakeCompleted(1, stdout="", stderr=stderr)

    resp = _post(client, action)

    # Failure is a normal response body, NOT a 500 — this is the error-toast path.
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["output"] == stderr  # stdout ("") + stderr
    # app.js toasts _firstLine(output); a non-empty first line must exist.
    assert body["output"].splitlines()[0]


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


def test_endpoint_output_is_stdout_then_stderr(client, fake_owm):
    """The combined-stream contract: stdout precedes stderr in `output`."""
    fake_owm.result = _FakeCompleted(1, stdout="pushing...\n", stderr="rejected\n")

    resp = _post(client, "push")

    assert resp.json()["output"] == "pushing...\nrejected\n"


def test_owm_passes_workspace_as_cwd_and_env(fake_owm):
    """Unit-level: _owm pins cwd + OWM_WORKSPACE to the target workspace."""
    server._owm(Path("/tmp/ws"), "status")

    kwargs = fake_owm.calls[0]["kwargs"]
    assert kwargs["cwd"] == "/tmp/ws"
    assert kwargs["env"]["OWM_WORKSPACE"] == "/tmp/ws"
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
