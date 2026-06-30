#!/usr/bin/env python3
"""
Seed a minimal owm workspace for local exploration.

Usage:
    python scripts/seed_ws.py [TARGET_DIR] [--odoo-repo PATH]

    TARGET_DIR      Where to create the workspace (default: ~/tmp/owm-test-ws)
    --odoo-repo     Path to an existing bare odoo repo to symlink in, e.g.
                    ../dev-instances/_repos/odoo.git
                    If omitted, a toy odoo repo (one commit) is created instead.
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

RUNNABLE_REPOS = Path(__file__).resolve().parent.parent / "test_fixtures" / "runnable-repos"


def run(cmd: list[str], cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True)


def _git_commit_bare(src: Path, target: Path, message: str) -> None:
    """Turn a populated source dir into a committed repo + a bare clone."""
    run(["git", "init", "-q", "-b", "main"], cwd=src)
    run(["git", "config", "user.email", "seed@owm.test"], cwd=src)
    run(["git", "config", "user.name", "owm-seed"], cwd=src)
    run(["git", "add", "-A"], cwd=src)
    run(["git", "commit", "-q", "-m", message], cwd=src)
    run(["git", "clone", "--bare", "-q", str(src), str(target)])


def make_toy_repo(upstream_dir: Path, name: str, target: Path) -> None:
    src = upstream_dir / name
    src.mkdir(parents=True, exist_ok=True)
    (src / "README.md").write_text(f"# {name}\n")
    _git_commit_bare(src, target, "seed: initial")


def seed_runnable_repo(upstream_dir: Path, name: str, target: Path) -> None:
    """Materialise a runnable addon repo from test_fixtures/runnable-repos/<name>/."""
    fixture = RUNNABLE_REPOS / name
    if not fixture.is_dir():
        print(f"error: no runnable fixture at {fixture}", file=sys.stderr)
        sys.exit(1)
    src = upstream_dir / name
    shutil.copytree(fixture, src, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    _git_commit_bare(src, target, "seed: runnable fixture")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target_dir", nargs="?", default=None, help="Workspace directory to create")
    parser.add_argument("--odoo-repo", metavar="PATH", help="Path to an existing bare odoo repo")
    parser.add_argument(
        "--with-addons",
        action="store_true",
        help="Seed runnable product-core + product-ext repos (cross-repo inherit/override smoke) "
        "instead of an empty toy product-core. Needs a real --odoo-repo to actually boot.",
    )
    args = parser.parse_args()

    ws = Path(args.target_dir).expanduser().resolve() if args.target_dir else Path.home() / "tmp" / "owm-test-ws"

    if ws.exists():
        print(f"error: {ws} already exists — remove it first or pass a different path.", file=sys.stderr)
        print(f"       rm -rf {ws}", file=sys.stderr)
        sys.exit(1)

    odoo_repo: Path | None = None
    if args.odoo_repo:
        odoo_repo = Path(args.odoo_repo).expanduser().resolve()
        if not odoo_repo.is_dir():
            print(f"error: --odoo-repo path does not exist: {odoo_repo}", file=sys.stderr)
            sys.exit(1)

    print(f"Seeding workspace at {ws} ...")

    for d in ["instances", "_repos", "_shared", "_dumps", "_archive", "_proxy"]:
        (ws / d).mkdir(parents=True)
    (ws / "owm.log").touch()

    upstream = ws / "_upstream"

    # odoo: symlink to real repo, or toy
    if odoo_repo:
        (ws / "_repos" / "odoo.git").symlink_to(odoo_repo)
        odoo_ref = str(odoo_repo)
        print(f"  + _repos/odoo.git -> {odoo_repo} (symlink)")
    else:
        make_toy_repo(upstream, "odoo", ws / "_repos" / "odoo.git")
        odoo_ref = str(ws / "_repos" / "odoo.git")
        print("  + _repos/odoo.git (toy)")

    # product-core (+ product-ext): runnable addon repos, or an empty toy
    if args.with_addons:
        seed_runnable_repo(upstream, "product-core", ws / "_repos" / "product-core.git")
        seed_runnable_repo(upstream, "product-ext", ws / "_repos" / "product-ext.git")
        product_core_ref = str(ws / "_repos" / "product-core.git")
        product_ext_ref = str(ws / "_repos" / "product-ext.git")
        print("  + _repos/product-core.git (runnable: product_base)")
        print("  + _repos/product-ext.git (runnable: product_ext, _inherits product.probe)")
        shutil.copy(RUNNABLE_REPOS / "smoke_inherit.py", ws / "smoke_inherit.py")
        print("  + smoke_inherit.py")
        # addon-contributing repos must declare has_addons (default is False).
        repos_block = (
            f'odoo         = {{path = "{odoo_ref}", has_addons = true, addons_paths = ["odoo/addons", "addons"]}}\n'
            f'product-core = {{path = "{product_core_ref}", has_addons = true}}\n'
            f'product-ext  = {{path = "{product_ext_ref}", has_addons = true}}\n'
        )
    else:
        make_toy_repo(upstream, "product-core", ws / "_repos" / "product-core.git")
        product_core_ref = str(ws / "_repos" / "product-core.git")
        print("  + _repos/product-core.git (toy)")
        repos_block = (
            f'odoo         = "{odoo_ref}"\n'
            f'product-core = "{product_core_ref}"\n'
        )

    (ws / "workspace.toml").write_text(
        f"[repos]\n"
        f"{repos_block}"
        f"\n"
        f"[clusters]\n"
        f'"19" = {{pg_version = "16", port = 5432}}\n'
        f"\n"
        f"[defaults]\n"
        f'instances_dir = "instances"\n'
    )
    print("  + workspace.toml")

    odoo_branch = "19.0" if odoo_repo else "main"
    if args.with_addons:
        print(f"""
Done. Cross-repo inherit/override smoke:

  cd {ws}

  # Materialise an instance pulling odoo + both addon repos (needs postgres on 5432).
  # +create on the addon repos: their feat-test branch is created from main.
  owm create feat-test odoo={odoo_branch}:shared product-core=feat-test:main+create product-ext=feat-test:main+create
  owm install feat-test product_ext        # pulls product_base in via depends (instance stopped)

  # Run the smoke through odoo-bin shell — expect every case OK:
  owm shell feat-test --script smoke_inherit.py --json

Note: run owm via 'uv run owm' if it's not on PATH.
""")
    else:
        print(f"""
Done. Try it:

  cd {ws}

  # Write an instance.toml (no I/O, always safe):
  owm create feat-test odoo={odoo_branch}:shared product-core=feat-test:main --toml-only

  # Inspect what was written:
  cat instances/feat-test/instance.toml

  # Materialise (requires postgres on port 5432):
  owm create feat-test

  # From inside the instance dir — no name needed:
  cd instances/feat-test
  owm status

Note: run owm via 'uv run owm' if it's not on PATH.
""")


if __name__ == "__main__":
    main()
