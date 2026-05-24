# re-owm setup

> This doc is a living record — fill in gaps as you encounter them.
> Docker support is planned but not yet available; this covers local setup only.

---

## System dependencies

| Dependency | Min version | Notes |
|---|---|---|
| Python | 3.12 | Required by the project |
| [uv](https://docs.astral.sh/uv/) | any recent | Package manager; replaces pip/venv |
| git | 2.x | Worktree support needed |
| PostgreSQL | 14+ | Only needed for full instance materialisation |

Python packages (`click`, `psutil`, etc.) are installed automatically by `uv sync`.

---

## Are you on...

### WSL (Windows)
Treat as Linux. PostgreSQL must be running inside WSL, not on the Windows host.
`/var/run/postgresql` must be accessible (default on Ubuntu).

### Linux (Ubuntu / Omarchy)
Main supported target. Steps below apply directly.

### macOS
Not tested yet. PostgreSQL socket path likely differs (`/tmp` instead of `/var/run/postgresql`).
Should work with minor config changes once attempted.

### Docker
Not yet available. Planned for a future pass.

---

## Install

```bash
git clone <repo> re-owm
cd re-owm
uv sync
```

Verify:
```bash
uv run owm --help
```

---

## Set up a development workspace

A workspace is a directory that re-owm manages — it holds repo clones, instance configs, and postgres databases.

### Option A: seed a fresh workspace (recommended for local dev)

```bash
# Toy repos only (no real Odoo source):
uv run python scripts/seed_ws.py ~/path/to/owm-ws

# With a real Odoo bare repo (faster worktree adds, real branches):
uv run python scripts/seed_ws.py ~/path/to/owm-ws \
  --odoo-repo ../dev-instances/_repos/odoo.git
```

This creates the directory structure, seeds bare repos, and writes a `workspace.toml`.

### Option B: point at an existing workspace

If you already have a workspace (e.g. `dev-instances`), just pass it as `--workspace` to any `owm` command, or `cd` into an instance directory and owm will infer it.

---

## Create your first instance (toml-only, no I/O)

```bash
cd ~/path/to/owm-ws
uv run owm create feat-test odoo=19.0:shared product-core=feat-test:main --toml-only
cat instances/feat-test/instance.toml
```

`--toml-only` writes the config and stops — safe to run anywhere, no postgres or git needed.

---

## Materialise an instance (requires postgres)

```bash
uv run owm create feat-test
```

This clones/links repos, creates the postgres database, sets up the venv, and writes `instance.conf`.

PostgreSQL must be reachable at the socket configured in `workspace.toml` (default: port 5432, socket at `/var/run/postgresql`).

---

## Run tests

```bash
# Full suite (unit + smoke; skips postgres tests if pg not running):
uv run pytest

# Unit only (no external deps):
uv run pytest -m "not integration and not smoke"

# With postgres available:
uv run pytest
```
