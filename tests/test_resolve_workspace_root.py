"""
Workspace-root resolution precedence: override > OWM_WORKSPACE > cwd-walkup.

Mirrors owm's locked baseline (a deliberate signal beats the incidental cwd,
git-style). The conftest autouse fixture points OWM_WORKSPACE at a sentinel dir;
these tests need full control of it, so the local autouse fixture clears it and the
cases that exercise the env branch set it explicitly via monkeypatch.
"""
import pytest

from owm.config import resolve_workspace_root, cwd_workspace_conflict
from owm.errors import OwmError, NOT_FOUND


@pytest.fixture(autouse=True)
def _clear_owm_workspace(_isolate_owm_workspace, monkeypatch):
    # depends on the conftest sentinel-setter so this clear runs after it
    monkeypatch.delenv("OWM_WORKSPACE", raising=False)


@pytest.mark.config_schemas
def test_override_beats_env_and_cwd(tmp_path, monkeypatch):
    ws = tmp_path / "cwd_ws"
    ws.mkdir()
    (ws / "workspace.toml").write_text("")
    monkeypatch.setenv("OWM_WORKSPACE", str(tmp_path / "env_ws"))
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
    monkeypatch.setenv("OWM_WORKSPACE", str(env_ws))
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


@pytest.mark.config_schemas
def test_conflict_detects_shadowed_cwd_workspace(tmp_path, monkeypatch):
    cwd_ws = tmp_path / "cwd_ws"
    cwd_ws.mkdir()
    (cwd_ws / "workspace.toml").write_text("")
    other_ws = tmp_path / "other_ws"
    other_ws.mkdir()
    (other_ws / "workspace.toml").write_text("")
    monkeypatch.chdir(cwd_ws)
    # operating on other_ws while standing in cwd_ws → conflict names cwd_ws
    assert cwd_workspace_conflict(str(other_ws)) == str(cwd_ws)


@pytest.mark.config_schemas
def test_conflict_none_when_cwd_is_resolved_root(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    (ws / "instances").mkdir(parents=True)
    (ws / "workspace.toml").write_text("")
    monkeypatch.chdir(ws / "instances")
    assert cwd_workspace_conflict(str(ws)) is None


@pytest.mark.config_schemas
def test_conflict_none_when_cwd_in_no_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cwd_workspace_conflict(str(tmp_path / "somewhere")) is None
