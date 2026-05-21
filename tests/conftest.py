"""
Shared pytest fixtures for re-owm integration and smoke tests.

Fixture tiers:
  - git primitives: make_upstream_repo, make_bare_clone, git_commit
  - workspace: tmp_workspace, workspace_toml, instance_toml
  - repo seeds: fixture_repo_path (serves test_fixtures/repos/* content)

When wiring up red tests that need real filesystem/git state, import
fixtures from here rather than building git setup inline. Tests that
only need to assert on pure function output can ignore this file.

Lifecycle note: fixtures that create instances/DBs/worktrees need the
real owm functions to exist before they can be used. Stubs in test files
suffice for the red phase; swap for real imports when going green.
"""

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

FIXTURE_REPOS = Path(__file__).parent.parent / "test_fixtures" / "repos"


# ---------------------------------------------------------------------------
# Git primitives
# ---------------------------------------------------------------------------

def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _git_config(repo_path):
    """Set throwaway identity so commits don't need a real git config."""
    _git("config", "user.email", "test@owm.test", cwd=repo_path)
    _git("config", "user.name", "owm-test", cwd=repo_path)


@pytest.fixture
def git_commit():
    """
    Helper callable: commit all staged/unstaged changes in a repo.

    Usage:
        git_commit(repo_path, message="add feature")
    """
    def _commit(repo_path: Path, message: str = "test commit", files: dict | None = None):
        repo_path = Path(repo_path)
        if files:
            for rel_path, content in files.items():
                dest = repo_path / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content)
        _git("add", ".", cwd=repo_path)
        _git("commit", "--allow-empty", "-m", message, cwd=repo_path)
    return _commit


@pytest.fixture
def make_upstream_repo(tmp_path, git_commit):
    """
    Factory: initialise a real git repo seeded with content.

    Args:
        name: repo name (used as subdirectory under tmp_path/_upstream/)
        seed: "fixture" uses test_fixtures/repos/<name>/ content;
              dict maps relative paths to file content strings;
              None creates an empty repo with a single README commit.

    Returns the Path to the upstream repo.
    """
    def _make(name: str, seed=None) -> Path:
        upstream = tmp_path / "_upstream" / name
        upstream.mkdir(parents=True)
        _git("init", "-b", "main", cwd=upstream)
        _git_config(upstream)

        if seed == "fixture":
            fixture_path = FIXTURE_REPOS / name
            if not fixture_path.exists():
                raise FileNotFoundError(
                    f"No test fixture for repo '{name}' at {fixture_path}"
                )
            shutil.copytree(fixture_path, upstream, dirs_exist_ok=True)
            git_commit(upstream, message=f"seed from fixture: {name}")
        elif isinstance(seed, dict):
            git_commit(upstream, message="seed from dict", files=seed)
        else:
            git_commit(upstream, message="initial commit", files={"README.md": f"# {name}\n"})

        return upstream
    return _make


@pytest.fixture
def make_bare_clone(tmp_path):
    """
    Factory: create a bare clone of an upstream repo, as owm init would.

    Returns the Path to the bare clone (name ends in .git by convention).
    """
    def _make(upstream_path: Path, name: str | None = None) -> Path:
        name = name or Path(upstream_path).name
        bare = tmp_path / "_repos" / f"{name}.git"
        bare.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--bare", str(upstream_path), str(bare)],
            check=True, capture_output=True,
        )
        return bare
    return _make


@pytest.fixture
def make_worktree(git_commit):
    """
    Factory: check out a worktree from a bare repo at a given path/branch.

    Returns the Path to the worktree.
    """
    def _make(bare_path: Path, worktree_path: Path, branch: str = "main") -> Path:
        worktree_path = Path(worktree_path)
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "worktree", "add", str(worktree_path), branch],
            cwd=bare_path, check=True, capture_output=True,
        )
        return worktree_path
    return _make


# ---------------------------------------------------------------------------
# Workspace skeleton
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_workspace(tmp_path):
    """
    Minimal owm workspace directory structure, no repos cloned yet.

    Layout:
        tmp_path/workspace/
            instances/
            _repos/
            _shared/
            _dumps/
            _archive/
            owm.log  (empty)
    """
    ws = tmp_path / "workspace"
    for subdir in ("instances", "_repos", "_shared", "_dumps", "_archive"):
        (ws / subdir).mkdir(parents=True)
    (ws / "owm.log").touch()
    return ws


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def workspace_toml(
    repos: dict,
    repo_meta: dict | None = None,
    clusters: dict | None = None,
    defaults: dict | None = None,
    patches: dict | None = None,
    compare_pairs: list | None = None,
) -> str:
    """
    Build a workspace.toml string from dicts.

    repos: {"name": "git-url"}
    repo_meta: {"name": {"has_addons": True, "addons_paths": ["addons"]}}
    clusters: {"19": {"pg_version": "16", "port": 5432}}
    """
    clusters = clusters or {"19": {"pg_version": "16", "port": 5432}}
    repo_meta = repo_meta or {}

    lines = ["[repos]"]
    for name, url in repos.items():
        lines.append(f'{name} = "{url}"')

    if repo_meta:
        lines.append("\n[repos.meta]")
        for repo, meta in repo_meta.items():
            for key, val in meta.items():
                if isinstance(val, list):
                    rendered = "[" + ", ".join(f'"{v}"' for v in val) + "]"
                    lines.append(f"{repo}.{key} = {rendered}")
                elif isinstance(val, bool):
                    lines.append(f"{repo}.{key} = {'true' if val else 'false'}")
                else:
                    lines.append(f"{repo}.{key} = {val!r}")

    lines.append("\n[clusters]")
    for ver, cfg in clusters.items():
        lines.append(
            f'"{ver}" = {{pg_version = "{cfg["pg_version"]}", port = {cfg["port"]}}}'
        )

    if defaults:
        lines.append("\n[defaults]")
        for k, v in defaults.items():
            if isinstance(v, list):
                lines.append(f"{k} = [{', '.join(str(x) for x in v)}]")
            else:
                lines.append(f"{k} = {v!r}")

    if patches:
        lines.append("\n[patches]")
        for ver, files in patches.items():
            rendered = "[" + ", ".join(f'"{f}"' for f in files) + "]"
            lines.append(f'"{ver}" = {rendered}')

    if compare_pairs:
        lines.append("\n[compare_pairs]")
        rendered = "[" + ", ".join(f'["{a}", "{b}"]' for a, b in compare_pairs) + "]"
        lines.append(f"pairs = {rendered}")

    return "\n".join(lines) + "\n"


def _spec_to_inline_table(spec: str) -> str:
    """Convert string DSL spec to TOML inline-table string for on-disk fixtures."""
    colon = spec.index(":")
    branch = spec[:colon]
    parts = spec[colon + 1:].split("+")
    base_or_flag, flags = parts[0], set(parts[1:])
    kvs = [f'branch = "{branch}"']
    if base_or_flag == "shared":
        kvs.append("shared = true")
    else:
        kvs.append(f'base = "{base_or_flag}"')
    if "readonly" in flags:
        kvs.append("readonly = true")
    if "exists" in flags:
        kvs.append("exists = true")
    if "create" in flags:
        kvs.append("create = true")
    return "{" + ", ".join(kvs) + "}"


def instance_toml(
    repos: dict,
    db_name: str,
    pg_port: int = 5432,
    http_port: int = 8142,
    workers: int = 2,
    template: str | None = None,
    modules: list | None = None,
    python_version: str | None = None,
) -> str:
    """
    Build an instance.toml string using inline-table repo specs.

    repos: {"name": "branch:base+flags"}  — string DSL, emitted as inline-table on disk
    """
    lines = ["[repos]"]
    for name, spec in repos.items():
        lines.append(f"{name} = {_spec_to_inline_table(spec)}")

    lines.append("\n[database]")
    lines.append(f'name = "{db_name}"')
    lines.append(f"pg_port = {pg_port}")
    if template:
        lines.append(f'template = "{template}"')

    lines.append("\n[server]")
    lines.append(f"http_port = {http_port}")
    lines.append(f"gevent_port = {http_port + 1}")
    lines.append(f"workers = {workers}")

    if modules:
        lines.append("\n[install]")
        rendered = "[" + ", ".join(f'"{m}"' for m in modules) + "]"
        lines.append(f"modules = {rendered}")

    if python_version:
        lines.append("\n[python]")
        lines.append(f'version = "{python_version}"')

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Full workspace fixture (repos cloned, toml written)
# ---------------------------------------------------------------------------

@pytest.fixture
def standard_workspace(tmp_workspace, make_upstream_repo, make_bare_clone):
    """
    A workspace with three repos (product_core, customer_config, odoo_like)
    cloned as bare repos and workspace.toml written.

    odoo_like uses addons_paths = ["addons", "odoo/addons"] to exercise
    multi-path resolution.

    Returns a namespace with:
        .root           workspace root Path
        .bare_repos     {name: bare_path}
        .upstream_repos {name: upstream_path}
        .toml_path      Path to workspace.toml
        .toml_str       raw toml string
    """
    from types import SimpleNamespace

    upstreams = {
        "product_core":    make_upstream_repo("product_core",   seed="fixture"),
        "customer_config": make_upstream_repo("customer_config", seed="fixture"),
        "odoo_like":       make_upstream_repo("odoo_like",      seed="fixture"),
        "scripts_repo":    make_upstream_repo("scripts_repo",   seed="fixture"),
    }
    bares = {name: make_bare_clone(path, name) for name, path in upstreams.items()}

    toml_str = workspace_toml(
        repos={name: str(path) for name, path in bares.items()},
        repo_meta={
            "product_core":    {"has_addons": True},
            "customer_config": {"has_addons": True},
            "odoo_like":       {"has_addons": True, "addons_paths": ["addons", "odoo/addons"]},
            "scripts_repo":    {"has_addons": False},
        },
    )
    toml_path = tmp_workspace / "workspace.toml"
    toml_path.write_text(toml_str)

    return SimpleNamespace(
        root=tmp_workspace,
        bare_repos=bares,
        upstream_repos=upstreams,
        toml_path=toml_path,
        toml_str=toml_str,
    )


@pytest.fixture
def standard_instance_toml(tmp_workspace):
    """
    Writes a minimal instance.toml for 'feat-789' to tmp_workspace/instances/feat-789/.
    Returns the Path to the written file.
    """
    inst_dir = tmp_workspace / "instances" / "feat-789"
    inst_dir.mkdir(parents=True, exist_ok=True)
    content = instance_toml(
        repos={
            "odoo_like":       "main:shared",
            "product_core":    "feat-789-dev:main",
            "customer_config": "feat-789-dev:main",
        },
        db_name="owm_test_feat789",
        http_port=8142,
        modules=["test_sale_ext", "test_customer_addon"],
        python_version="3.12",
    )
    path = inst_dir / "instance.toml"
    path.write_text(content)
    return path
