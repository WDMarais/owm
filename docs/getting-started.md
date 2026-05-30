# Getting started with owm

owm manages Odoo development workspaces: it clones repos, provisions Postgres clusters, maintains git worktrees per instance, and generates Odoo configuration files. This guide walks through a complete setup from a fresh machine to a running instance.

---

## What owm does and doesn't do

owm manages:
- Bare git repo clones (`_repos/`)
- Git worktrees per instance (`_shared/`, `instances/<name>/`)
- Postgres cluster provisioning (`pg_createcluster`, `pg_ctlcluster`)
- Postgres superuser role for the operator
- Instance configuration (`instance.conf`)
- Reverse-proxy block generation (`_proxy/`)
- Python venvs per instance

owm does **not** manage:
- OS-level package installation (PostgreSQL, git, uv, nginx/caddy)
- DNS or `/etc/hosts` entries for `*.localhost` routing
- SSL certificates
- Nginx/caddy installation or daemon management

---

## System prerequisites

Install these before running `owm init`:

```bash
# Debian/Ubuntu
sudo apt install git postgresql postgresql-common

# uv (Python package manager — replaces pip/venv)
curl -LsSf https://astral.sh/uv/install.sh | sh
```

| Dependency   | Min version | Notes |
|---|---|---|
| git          | 2.x         | Worktree support required |
| PostgreSQL   | 14+         | `pg_createcluster` must be available; owm manages clusters |
| uv           | any recent  | Required to install owm and build instance venvs |

> **WSL note:** PostgreSQL must run inside WSL, not on the Windows host.
> `/var/run/postgresql` must be accessible (default on Ubuntu).

---

## Install owm

```bash
# From a cloned copy (development / contributor):
git clone <repo> owm
cd owm
uv tool install -e .

# Verify:
owm --help
```

---

## Set up a workspace

A workspace is a directory owm manages. Everything lives under it: repo clones, instance configs, databases (by reference), proxy blocks.

### 1. Create the directory and write workspace.toml

```bash
mkdir ~/my-workspace
cd ~/my-workspace
```

Create `workspace.toml`:

```toml
# Repos — table form required when declaring addons metadata
[repos.odoo]
path         = "git@github.com:odoo/odoo.git"
has_addons   = true
addons_paths = ["odoo/addons", "addons"]

[repos.customer-config]
path         = "git@github.com:your-org/customer-config.git"
has_addons   = true
addons_paths = ["."]          # addons at repo root — the common case

# Simple string form is valid for repos with no Odoo addons:
# scripts = "git@github.com:your-org/scripts.git"

[clusters]
# Key is the Odoo major version this cluster serves.
# owm will create and start the cluster if it doesn't exist.
"19" = {pg_version = "16", port = 5432}

[defaults]
http_port_range = [8100, 8299]
workers = 2

[proxy]
domain_suffix = "localhost"
backend = "nginx"             # or "caddy"
```

> **Repo table vs string form:** use the table form (`[repos.<name>]`) for any repo that
> contains Odoo addons — it lets you declare `has_addons` and `addons_paths` explicitly.
> The string shorthand (`name = "url"`) is for repos with no addons metadata (scripts,
> tooling, etc.). `owm validate` will warn about repos missing addons metadata if they
> appear to contain modules.

### 2. Run owm init

```bash
owm init
```

This will:
- Create `_repos/`, `_shared/`, `instances/`, `_archive/`, `_dumps/`, `_proxy/`, `owm.log`
- Bare-clone every repo declared in `[repos]`
- Check whether the declared Postgres cluster is reachable; if not, create and start it
- Ensure the operator superuser role exists in Postgres
- Write a proxy stub to `_proxy/` with instructions for wiring into nginx or caddy

If you already have the repos cloned locally (e.g. migrating from an existing workspace):

```bash
owm init --local-copies /path/to/old-workspace
```

owm looks for `_repos/<name>.git` under that path and copies from disk instead of
downloading. The full object store is copied (no shared references); the remote URL is
updated to the upstream URL from workspace.toml.

`owm init` is idempotent — safe to re-run. Existing repos and running clusters are skipped.

### 3. Wire up the reverse proxy (optional)

owm generates per-instance proxy blocks under `_proxy/`. To use them, wire the include
file into your nginx or caddy config as shown in `_proxy/owm-include.conf` (nginx) or
`_proxy/00-owm-include.caddy` (caddy).

For local `*.localhost` routing without a proxy, add entries to `/etc/hosts` manually,
or use a local DNS resolver that resolves `*.localhost` to `127.0.0.1`.

---

## Set up a base template (recommended before creating instances)

The base template is a Postgres database with Odoo's core modules installed. Instances
point to it so that `owm db-reset` can restore a clean state in seconds rather than
re-running a full module install.

### Create and install the template

```bash
# 1. Create the template instance config
owm create odoo19-base odoo=19.0:shared --toml-only

# 2. Edit instances/odoo19-base/instance.toml — change the db name to your template name:
#    [database]
#    name = "odoo19_base"
#    ...

# 3. Install base modules (instance must be stopped — owm install starts its own process)
owm install odoo19-base base web mail
```

The template DB (`odoo19_base`) now exists in Postgres. You can add any modules that
every instance needs. `owm install` always leaves the instance stopped when done.

> You don't need to `owm start` the template instance day-to-day. It just needs to exist
> as a Postgres database. You can archive or delete the template *instance* config once
> you're done setting it up — the DB stays.

### Point working instances at the template

Add `template` to `[database]` in any instance.toml you want to be resettable:

```toml
[database]
name     = "feat-789"
pg_port  = 5432
template = "odoo19_base"
```

Then reset at any time:

```bash
owm stop feat-789
owm db-reset feat-789   # drops feat-789, clones from odoo19_base
owm start feat-789
```

Reset is a Postgres `CREATE DATABASE ... TEMPLATE` operation — fast regardless of DB size.

---

## Create your first working instance

### Generate instance.toml (no I/O — always safe to run)

```bash
owm create feat-789 odoo=19.0:shared --toml-only
cat instances/feat-789/instance.toml
```

The `odoo=19.0:shared` argument means: use branch `19.0` of the `odoo` repo as a
**shared** worktree (all instances on the same branch share one checkout under `_shared/`).

Review the generated toml and add `template` before materialising if you set one up above.

### Materialise

```bash
owm create feat-789
```

This creates:
- Git worktree(s) — shared ones under `_shared/<repo>/<branch>`, per-instance under `instances/<name>/<repo>/`
- Python venv at `instances/feat-789/.venv` (built from the repo's `requirements.txt`)
- Postgres database `feat-789`
- Reverse-proxy block at `_proxy/feat-789.conf`
- Odoo config at `instances/feat-789/instance.conf`

`owm create` is idempotent — re-running with an unchanged toml is a no-op.

---

## Start / stop / status

```bash
owm start feat-789
owm status feat-789
owm stop feat-789
```

From inside the instance directory (owm infers workspace and name from CWD):

```bash
cd instances/feat-789
owm start
owm status
```

If start fails with `port N is already in use [PORT_CONTESTED]`, another process holds
that port. owm only manages processes it started — orphaned processes from other workspaces
need to be cleared manually:

```bash
lsof -i :8100     # find what's holding the port
kill <pid>
```

---

## Day-to-day operations

### Install modules

```bash
owm stop feat-789
owm install feat-789 sale purchase account   # installs + appends to [install].modules
owm start feat-789
```

`owm install` runs Odoo with `-i` and leaves the instance stopped. Stop first, start
again after.

Modules are appended to `[install].modules` in `instance.toml` automatically, so the
toml always reflects what this instance has installed. Duplicates are ignored.

To install without recording to the toml (ephemeral, e.g. debugging):

```bash
owm install feat-789 some_module --no-save
```

To re-install everything declared in the manifest (e.g. after `db-reset`):

```bash
owm install feat-789   # no modules listed → installs from [install].modules
```

`owm install` uses Odoo's `-i` flag — it's a no-op for modules already installed in the
DB. To update already-installed modules, use `owm upgrade` instead:

```bash
owm upgrade feat-789 sale          # -u sale
owm upgrade feat-789               # -u all installed modules
owm upgrade feat-789 sale --reinstall  # force reinstall
```

### Reset the database

```bash
owm stop feat-789
owm db-reset feat-789      # clone from template — fast regardless of DB size
owm install feat-789       # re-apply module manifest from [install].modules
owm start feat-789
```

Requires `template` configured in `[database]` of `instance.toml`. The install step
re-applies whatever was recorded in the manifest — no need to remember which modules
the instance had.

### Inspect logs

```bash
owm logs feat-789           # last 50 lines
owm logs feat-789 -n 200    # last 200 lines
owm logs feat-789 --follow  # tail -f (live stream)
```

### Fetch upstream changes

```bash
owm fetch
```

Fetches only the branches currently referenced by active instances — not all remote
branches. This keeps fetches fast even for large repos like odoo.

### Archive and unarchive

Archiving suspends an instance: strips its port reservations, dumps its database, and moves everything to `_archive/`. The workspace port slots are freed for other instances.

```bash
owm stop feat-789
owm archive feat-789
# → _archive/feat-789/ with instance.toml (ports stripped) + db.dump + instance.log
```

Restore it later from any workspace that has the same cluster:

```bash
owm unarchive feat-789
# → rematerialises worktrees/venv/proxy, assigns fresh ports, restores DB
owm start feat-789
```

Pass `--discard` to remove the archive directory after a successful restore:

```bash
owm unarchive feat-789 --discard
```

> `_archive/` is for suspended instances. `_dumps/` is for intentional exports you want to
> keep around — e.g. a known-good snapshot before a risky migration. Use `owm db-dump` for
> those.

### Delete an instance

```bash
owm delete feat-789
```

Prompts for confirmation, then removes worktrees, drops the database, removes the proxy
block, and deletes the instance directory. This is permanent — archive first if you might
want the instance back.

```
  • all instance data will be permanently deleted
Delete 'feat-789'? [y/N]:
```

Skip the prompt in scripts with `--force`:

```bash
owm delete feat-789 --force
```

### Other useful commands

```bash
owm list                    # running instances in this workspace
owm health feat-789         # HTTP + DB reachability check
owm env feat-789            # print env vars (paths, ports, db name)
owm validate feat-789       # config consistency check
owm push feat-789           # push instance branches to origin
owm db-dump feat-789        # dump database to _dumps/
```

---

## End-to-end quick reference

Minimal command sequence from a fresh workspace to a deleted instance:

```bash
mkdir ~/my-workspace && cd ~/my-workspace
# write workspace.toml (see above)

owm init

# Optional but recommended: set up a base template DB
owm create odoo19-base odoo=19.0:shared --toml-only
# edit instances/odoo19-base/instance.toml: set db name = "odoo19_base"
owm install odoo19-base base web mail

# Create a working instance
owm create feat-789 odoo=19.0:shared
owm start feat-789
owm status feat-789

# Install modules
owm stop feat-789
owm install feat-789 sale purchase account
owm start feat-789
owm logs feat-789 --follow

# Fetch upstream changes
owm fetch

# Reset to template
owm stop feat-789
owm db-reset feat-789
owm install feat-789   # re-applies [install].modules manifest
owm start feat-789

# Suspend (keeps DB, frees ports)
owm stop feat-789
owm archive feat-789

# Restore
owm unarchive feat-789
owm start feat-789

# Permanent removal
owm stop feat-789
owm delete feat-789
```

---

## Workspace layout reference

```
my-workspace/
├── workspace.toml          # workspace config — repos, clusters, proxy, defaults
├── owm.log                 # owm operation log
├── _repos/                 # bare git clones (the source of truth for all worktrees)
│   ├── odoo.git
│   └── customer-config.git
├── _shared/                # shared worktrees (one checkout per repo+branch)
│   └── odoo/
│       └── 19.0/
├── instances/              # one directory per instance
│   └── feat-789/
│       ├── instance.toml   # instance config (repos, ports, db, modules)
│       ├── instance.conf   # generated Odoo config — do not edit directly
│       ├── instance.log
│       └── .venv/
├── _proxy/                 # nginx/caddy include files — one per instance + the stub
├── _dumps/                 # database dumps
└── _archive/               # archived instances
```
