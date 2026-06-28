"""
Tests for the api.instance_diff and api.check_modules surfaces (CLI `owm diff`
/ `owm check-modules`, MCP owm_diff / owm_check_modules).

instance_diff runs real git against a temp worktree — no mocks. check_modules'
DB-querying path needs psql + a live DB, so only its config-only branches
(no modules declared) are covered here; the DB path is exercised by the
install/health smoke tests against a real cluster.
"""
import subprocess
from pathlib import Path

import pytest

from owm.api import instance_diff, check_modules
from owm.worktrees import resolve_worktree_path

from tests.conftest import instance_toml, FIXTURE_HTTP_PORT


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _write_instance(workspace_root: Path, instance: str, repos: dict, **kw) -> None:
    inst_dir = workspace_root / "instances" / instance
    inst_dir.mkdir(parents=True, exist_ok=True)
    (inst_dir / "instance.toml").write_text(
        instance_toml(repos=repos, db_name=f"owm_test_{instance}",
                      http_port=FIXTURE_HTTP_PORT, **kw)
    )


def _seed_worktree_with_feature(wt: Path) -> None:
    """A real git repo at `wt` with `main` (base) and the feature branch checked
    out, where the feature adds one file under a module directory."""
    wt.mkdir(parents=True, exist_ok=True)
    _git("init", "-b", "main", cwd=wt)
    _git("config", "user.email", "t@owm.test", cwd=wt)
    _git("config", "user.name", "owm-test", cwd=wt)
    (wt / "README.md").write_text("base\n")
    _git("add", ".", cwd=wt)
    _git("commit", "-m", "base", cwd=wt)
    _git("checkout", "-b", "feat-1-dev", cwd=wt)
    mod = wt / "product_core" / "models"
    mod.mkdir(parents=True)
    (mod / "thing.py").write_text("FIELD = 1\n")
    _git("add", ".", cwd=wt)
    _git("commit", "-m", "feature", cwd=wt)


# ---------------------------------------------------------------------------
# instance_diff
# ---------------------------------------------------------------------------

def test_diff_name_only_lists_changed_files_and_modules(tmp_workspace):
    _write_instance(tmp_workspace, "feat-1", {"product_core": "feat-1-dev:main"})
    wt = resolve_worktree_path("product_core", "feat-1-dev", False, str(tmp_workspace), "feat-1")
    _seed_worktree_with_feature(Path(wt.path))

    result = instance_diff("feat-1", str(tmp_workspace), mode="name-only")
    repo = result["repos"]["product_core"]
    assert repo["base"] == "main" and repo["branch"] == "feat-1-dev"
    assert "product_core/models/thing.py" in repo["files"]
    assert repo["modules"] == ["product_core"]
    assert "diff" not in repo and "stat" not in repo


def test_diff_patch_mode_includes_unified_patch(tmp_workspace):
    _write_instance(tmp_workspace, "feat-1", {"product_core": "feat-1-dev:main"})
    wt = resolve_worktree_path("product_core", "feat-1-dev", False, str(tmp_workspace), "feat-1")
    _seed_worktree_with_feature(Path(wt.path))

    result = instance_diff("feat-1", str(tmp_workspace), mode="patch")
    repo = result["repos"]["product_core"]
    assert "diff --git" in repo["diff"]
    assert "+FIELD = 1" in repo["diff"]


def test_diff_stat_mode_includes_diffstat(tmp_workspace):
    _write_instance(tmp_workspace, "feat-1", {"product_core": "feat-1-dev:main"})
    wt = resolve_worktree_path("product_core", "feat-1-dev", False, str(tmp_workspace), "feat-1")
    _seed_worktree_with_feature(Path(wt.path))

    result = instance_diff("feat-1", str(tmp_workspace), mode="stat")
    repo = result["repos"]["product_core"]
    assert "thing.py" in repo["stat"]
    assert "1 file changed" in repo["stat"]
    assert "diff" not in repo


def test_diff_skips_repo_with_no_base(tmp_workspace):
    _write_instance(tmp_workspace, "feat-1", {"odoo_like": "main:shared"})
    result = instance_diff("feat-1", str(tmp_workspace))
    assert result["repos"]["odoo_like"]["skipped"] == "no base configured"


def test_diff_skips_repo_with_missing_worktree(tmp_workspace):
    _write_instance(tmp_workspace, "feat-1", {"product_core": "feat-1-dev:main"})
    # worktree never created on disk
    result = instance_diff("feat-1", str(tmp_workspace))
    assert result["repos"]["product_core"]["skipped"] == "worktree not found"


# ---------------------------------------------------------------------------
# check_modules
# ---------------------------------------------------------------------------

def test_check_modules_notes_when_no_modules_declared(tmp_workspace):
    _write_instance(tmp_workspace, "feat-1", {"product_core": "feat-1-dev:main"})
    result = check_modules("feat-1", str(tmp_workspace))
    assert result["installed"] == [] and result["missing"] == []
    assert result["note"] == "no modules in [install]"
