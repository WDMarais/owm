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
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True)


def make_toy_repo(upstream_dir: Path, name: str, target: Path) -> None:
    src = upstream_dir / name
    src.mkdir(parents=True, exist_ok=True)
    run(["git", "init", "-q", "-b", "main"], cwd=src)
    run(["git", "config", "user.email", "seed@owm.test"], cwd=src)
    run(["git", "config", "user.name", "owm-seed"], cwd=src)
    (src / "README.md").write_text(f"# {name}\n")
    run(["git", "add", "README.md"], cwd=src)
    run(["git", "commit", "-q", "-m", "seed: initial"], cwd=src)
    run(["git", "clone", "--bare", "-q", str(src), str(target)])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target_dir", nargs="?", default=None, help="Workspace directory to create")
    parser.add_argument("--odoo-repo", metavar="PATH", help="Path to an existing bare odoo repo")
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

    # product-core: always toy
    make_toy_repo(upstream, "product-core", ws / "_repos" / "product-core.git")
    product_core_ref = str(ws / "_repos" / "product-core.git")
    print("  + _repos/product-core.git (toy)")

    (ws / "workspace.toml").write_text(
        f"[repos]\n"
        f'odoo         = "{odoo_ref}"\n'
        f'product-core = "{product_core_ref}"\n'
        f"\n"
        f"[clusters]\n"
        f'"19" = {{pg_version = "16", port = 5432}}\n'
        f"\n"
        f"[defaults]\n"
        f'instances_dir = "instances"\n'
    )
    print("  + workspace.toml")

    odoo_branch = "19.0" if odoo_repo else "main"
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
