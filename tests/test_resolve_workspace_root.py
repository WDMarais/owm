"""
Workspace-root resolution precedence: override > OWM_WORKSPACE > cwd-walkup.

Mirrors owm's locked baseline (a deliberate signal beats the incidental cwd,
git-style). The autouse fixture clears OWM_WORKSPACE so the real env spine
(~/dev-instances) can't leak into the walkup cases.
"""
import os
from unittest import mock

import pytest

from owm.config import resolve_workspace_root
from owm.errors import OwmError, NOT_FOUND


@pytest.fixture(autouse=True)
def _isolate_env():
    with mock.patch.dict(os.environ):
        os.environ.pop("OWM_WORKSPACE", None)
        yield


@pytest.mark.config_schemas
def test_override_beats_env_and_cwd(tmp_path, monkeypatch):
    ws = tmp_path / "cwd_ws"
    ws.mkdir()
    (ws / "workspace.toml").write_text("")
    os.environ["OWM_WORKSPACE"] = str(tmp_path / "env_ws")
    monkeypatch.chdir(ws)
    # override wins even though both the env var and the cwd are valid workspaces
    assert resolve_workspace_root(str(tmp_path / "override_ws")) == str(tmp_path / "override_ws")


@pytest.mark.config_schemas
def test_env_beats_cwd_walkup(tmp_path, monkeypatch):
    ws = tmp_path / "cwd_ws"
    ws.mkdir()
    (ws / "workspace.toml").write_text("")          # cwd IS a valid workspace
    env_ws = tmp_path / "env_ws"
    env_ws.mkdir()
    os.environ["OWM_WORKSPACE"] = str(env_ws)
    monkeypatch.chdir(ws)
    # the deliberate env var wins over the incidental cwd
    assert resolve_workspace_root() == str(env_ws)


@pytest.mark.config_schemas
def test_cwd_walkup_finds_workspace_from_subdir(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    (ws / "instances" / "feat-789").mkdir(parents=True)
    (ws / "workspace.toml").write_text("")
    monkeypatch.chdir(ws / "instances" / "feat-789")
    assert resolve_workspace_root() == str(ws)


@pytest.mark.config_schemas
def test_no_workspace_raises_not_found(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)   # no workspace.toml anywhere up the tree
    with pytest.raises(OwmError) as exc:
        resolve_workspace_root()
    assert exc.value.code == NOT_FOUND


@pytest.mark.config_schemas
def test_override_trusted_even_if_absent(tmp_path, monkeypatch):
    # override is returned as-is (abspath'd), not validated — matches owm
    monkeypatch.chdir(tmp_path)
    missing = tmp_path / "does_not_exist"
    assert resolve_workspace_root(str(missing)) == str(missing)
