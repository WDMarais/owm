# owm rewrite — behavioral spec

## Instance model

An instance is a named unit of work comprising:
- One worktree per configured repo, each on a designated branch
- A Postgres database
- A reserved HTTP port
- An Odoo config file
- Session context (markdown): happy-path setup/run instructions, exceptions, reviewer notes

Repos within an instance are either **per-instance** (branch owned/reviewed by this instance, writable) or **shared** (stable upstream branch, read-only by convention, shared across instances).

---

## Worktrees and branch ownership

```
create instance feat-789 with:
  odoo = "19.0"            shared=true   → uses shared worktree, no per-instance checkout
  product-core = "feat-789-dev"          → per-instance worktree, owned branch
  customer-config = "feat-789-dev"       → per-instance worktree, owned branch
→ instance directory created, worktrees linked, DB cloned from base template, port reserved
```

```
create instance review-101 with:
  odoo = "19.0"            shared=true
  product-core = "feat-789-dev"  readonly=true   → per-instance worktree, push disallowed
  customer-config = "feat-789-dev" readonly=true
→ same layout, but owm push refuses on product-core and customer-config
```

```
edit files in a readonly worktree
→ allowed — no hard block on local edits or commits
```

```
owm push review-101 product-core
→ refused: branch not configured as owned, no override flag set
```

```
owm push review-101 product-core --override
→ allowed if override flag explicitly set in instance config; disallowed otherwise
# senior pushing a fix onto a junior's PR is the intended exception case
```

```
shared worktree (odoo 19.0) edited and committed locally
→ flagged as unusual — warning that commits here are visible to all instances sharing this worktree
```

```
owm push <instance> <shared-repo>
→ refused; error message includes the raw git command to do it directly
# e.g. "shared worktrees are not managed by owm push — to push manually: git -C _shared/odoo/19.0 push origin 19.0"
# expertise filter: someone who understands the command can proceed; someone who doesn't knows to ask
```

---

## Database lifecycle

```
create instance feat-789, base template for 19.0 exists
→ DB cloned from template, skips full module reinstall
```

```
create instance feat-789, no base template exists for this odoo version
→ DB created from blank slate, full module install required; warning that this is slow
```

```
db-reset feat-789
→ DB restored from base template (same version); instance-specific seed script re-run if configured
```

```
db-reset feat-789, no seed script configured
→ DB restored from template only; user warned that instance-specific state is not restored
```

```
base template refresh triggered (manual or scheduled)
→ existing instances are NOT synced automatically
→ instances with template older than threshold get a staleness warning on next status check
# threshold: configurable, e.g. "template not synced in 30 days / 5 template versions"
```

```
instance opts in to template sync
→ DB backup created first; sync attempted; on failure, backup restored and error reported
```

```
instance does NOT opt in to template sync
→ no sync, no automatic action; staleness warning only
```

```
setup script for instance is idempotent and re-run on fresh template
→ expected happy path — design pressure is on idempotent scripts, not on keeping instances in sync
```

---

## Port assignment

Reserved range: [8100, 8299] for instance ports. [8090, 8099] reserved for owm-internal processes (dashboard, metrics, etc.).

```
create instance, ports 8100–8142 already in instance configs or bound by processes
→ assigned 8143; recorded in instance config
```

```
create instance, entire range [8100, 8299] exhausted
→ hard error: "port range exhausted — archive or delete unused instances to free ports"
# hitting ceiling indicates stale configs, not normal operation
```

```
start instance, configured port bound by an unrelated process
→ surfaces: process name, PID, command line
→ prompts user: "kill conflicting process, or reassign this instance to next free port?"
→ if reassign: instance config updated permanently to new port
→ if kill: user kills process, start proceeds on original port
# if user cares about a specific port, they kill; if not, reassign
```

```
port eviction (reassignment due to conflict) occurs
→ logged internally
```

```
port evictions exceed threshold (default: 10 in a rolling week)
→ owm surfaces recommendation to shift port range
# frequent evictions = port range overlapping something systemic
```

Port range and eviction threshold are configurable in workspace.toml; defaults are sane enough that most users never touch them.

**Migration from old-format instance.toml (single port):** existing instances have one port field; re-owm expects a pair (N, N+1). Migration strategy: manually update instance.toml files one-at-a-time, assigning N+1 = N+1 if free, or next available pair if not. No automatic migration — explicit per-instance update, done as instances are touched rather than in bulk.

Instance URL is a subdomain (`feat-789.localhost`) — port is an internal implementation detail not exposed in normal use. Cookie isolation is a side-effect benefit (browsers share jars per domain, not per port).

HTTPS is a first-class requirement (not deferred) — WebRTC/VoIP use cases require a secure context. Proxy choice (nginx vs caddy vs other) is an implementation decision deferred to Docker setup design; spec assumes subdomain model only. Local CA for `*.localhost` is implied by HTTPS requirement.

```
owm create feat-789
→ port auto-assigned from range, nginx block written, instance reachable at feat-789.localhost
# user never needs to know or specify the port
```

```
instance.toml specifies explicit port
→ owm honours it; warns if port conflicts with an existing non-running instance
→ hard error if port conflicts with a running instance
```

```
owm create feat-789 with pinned port already held by a stopped instance
→ warns: "port 8143 is reserved by review-101 (not running) — evict and reassign?"
→ if confirmed: review-101 gets next free port, feat-789 gets 8143
→ if declined: abort
```

```
owm create feat-789 with pinned port held by a running instance
→ hard error: cannot evict a running instance's port
```

---

## Instance lifecycle — create

```
owm new feat-789 --repos odoo:19.0:shared product-core:feat-789-dev customer-config:feat-789-dev
→ generates instance.toml with autofilled port, DB name, python version
→ no instance materialised yet — file is reviewable, statically validatable
```

```
owm create feat-789  (instance.toml exists, instance does not)
→ worktrees created, DB cloned from base template, port reserved, nginx block written, odoo.conf generated
```

```
owm create feat-789  (instance already exists, toml unchanged)
→ all steps skipped (idempotent); confirmation that instance is already up to date
```

```
owm create feat-789  (instance exists, branch changed for product-core in toml)
→ worktree for product-core switched to new branch in place if clean
→ if dirty: "product-core has uncommitted changes on feat-789-dev — switch anyway, stash first, or abort?"
```

```
owm create feat-789  (instance exists, new repo added to toml)
→ new worktree created; existing worktrees untouched
```

```
owm create feat-789  (instance exists, repo removed from toml)
→ worktree removed; branch remains in bare repo untouched
# removing a worktree never deletes a branch
```

---

## Workspace init

`owm init` is workspace-level only. System-level setup (Python, Postgres, system libs) handled by container/environment definition, not owm. One workspace per machine is the expected case; multiple workspaces each get their own `owm init` at their root.

```
owm init (fresh workspace)
→ bare clones from workspace.toml repo URLs
→ DB cluster provisioned per [clusters] config
→ reverse proxy block written for owm dashboard
→ local CA cert installed for *.localhost HTTPS
→ idempotent: skips anything already present
```

```
owm init (new repo added to workspace.toml)
→ clones new repo only; existing repos and clusters untouched
```

```
owm init (run in Docker context)
→ skips system-level steps (already handled by container); runs workspace steps only
```

---

## Addons resolution

Repos declared in `workspace.toml` with `has_addons = true` on repos that contribute Odoo modules. Explicit opt-in — better semantics over ergonomics (accidental inclusion harder to spot than accidental exclusion).

Repos declared in stability order in workspace.toml: `odoo → product-core → customer-config → scripts`. `addons_path` in generated `instance.conf` reverses this order for override specificity: `customer-config → product-core → odoo`.

Only repos explicitly listed in `instance.toml` contribute to addons_path — no implicit fallback to shared for absent repos. If product-core is not in the instance, it is not in addons_path. Silent exclusion, no warnings.

For repos present in instance but via shared worktree: addons path resolves to `_shared/<repo>/<branch>/addons` automatically.

```
instance with [odoo(shared), product-core(feat), customer-config(feat)]
→ addons_path = customer-config/addons, product-core/addons, _shared/odoo/19.0/addons, _shared/odoo/19.0/odoo/addons
```

```
instance with [odoo(shared), product-core(feat)] — customer-config excluded
→ addons_path = product-core/addons, _shared/odoo/19.0/addons, _shared/odoo/19.0/odoo/addons
# silent exclusion; no warning that customer-config has has_addons = true in workspace.toml
```

```
scripts repo in instance (has_addons not set)
→ not included in addons_path
```

## Requirements patching

Explicit patch declarations in workspace.toml per Python/Odoo version — not custom commits on repos we don't own.

```toml
[patches]
"12.0" = ["requirements_patches/odoo12_compat.txt"]
"19.0" = ["requirements_patches/odoo19_fix.txt"]
```

Patches are auditable, version-pinned, applied at venv install time. Patching a repo's requirements is a smell about upstream — owm accommodates it explicitly rather than hiding it.

---

## Ports — gevent and workers

Each instance gets two consecutive ports: HTTP (N) and gevent/longpolling (N+1). Effective instance capacity: 100 instances in range [8100, 8299].

Workers default: 2 (configurable per instance). Longpolling only active with workers > 0.
TODO: research optimal worker count and memory-per-worker implications before finalising default.

```
owm create feat-789
→ assigns ports 8142 (HTTP) and 8143 (gevent); both recorded in instance config
```

```
instance.conf generated with workers = 2, longpolling_port = N+1
```

---

## Venv management

uv is the canonical tool — required, not optional. Docker image includes it. Opt-out means user owns the consequences. No pip fallback by default.

Venv created on `owm create`, rebuilt on `owm venv-rebuild <instance>`, re-synced on `owm start` if requirements stamp has changed. Patches from workspace.toml applied at same points as requirements install.

```
owm create feat-789
→ venv created with Python version pinned per Odoo version
→ requirements installed via uv; workspace patches applied
→ stamp written (requirements hash + patch hash)
```

```
owm start feat-789, stamp unchanged
→ venv sync skipped
```

```
owm start feat-789, requirements changed since last stamp
→ uv sync run; patches reapplied; stamp updated
```

```
owm venv-rebuild feat-789
→ venv deleted and recreated from scratch; full install + patches
```

**Future optimisation (not now):** shared venv across instances on same Odoo version. Motivation: venv is ~370MB of ~400-460MB average instance size. Deferred — adds isolation complexity.

---

## Log rotation

Rotation trigger: 20k lines OR 1 week, whichever first.

**Local**: rotate and discard. No summarisation — statistical analysis on dev instances is overkill.

**owm-server** (opt-in): on rotation, headless summarisation pass — errors/warnings → statistics → Claude suggestion if signal found. User dispatches or declines; not automatic. Raw log retained only if actionable signal found; discarded if clean (happy path).

```
owm.log reaches 20k lines or 1 week threshold (local)
→ rotated and discarded
→ operational note: "if you want to retain log state, export explicitly within the rotation window"
```

```
owm.log rotated (owm-server, summarisation opt-in)
→ headless summarisation pass run
→ if suggestions found: raw log retained, user notified to dispatch or decline
→ if no signal: discarded silently
```

---

## Module install and upgrade

Template DB contains: base + configured core modules pre-installed.

On `owm create` and `owm start`: modules listed in `instance.toml [install]` installed if missing, plus dependencies and auto-installs. Already-installed modules skipped.

```
owm create feat-789 (modules in toml not yet installed)
→ odoo-bin called to install missing modules + dependencies
```

```
owm start feat-789 (all modules present)
→ module install step skipped
```

```
owm upgrade feat-789
→ stops instance; runs odoo-bin -u all; restarts
```

```
owm upgrade feat-789 --modules my_module,other_module
→ stops instance; runs odoo-bin -u my_module,other_module; restarts
```

```
owm upgrade feat-789 --reinstall
→ forces reinstall of all configured modules even if already present
```

Detection of new dependencies on already-installed modules is not automatic — happy path is "user knows to run owm upgrade after pulling a branch with manifest changes." owm does not diff manifests.

---

## owm env

Generated at call time from live instance state — always accurate, never stale.

```
owm env feat-789
→ prints resolved paths and binaries: ODOO_BIN, VENV_PYTHON, PSQL, DB_NAME, DB_PORT, INSTANCE_DIR, LOG_FILE, HTTP_PORT, GEVENT_PORT, etc.
```

```
owm env feat-789 --format dotenv
→ exports as KEY=value pairs, sourceable
```

```
owm env feat-789 --format json
→ machine-readable, agent-consumable
```

```
owm env feat-789 --format shell
→ export KEY=value lines, suitable for eval "$(owm env feat-789 --format shell)"
```

Dashboard equivalent: pre-filled copyable command buttons in right pane (psql connect string, odoo-bin shell invocation, log tail command, etc.) — same resolved values, one-click copy.

---

## Multi-user

One canonical user/registry state per workspace. Multiple users on the same machine are expected to use different instance names and ports — owm makes no special accommodation. On owm-server this remains the same: user coordination is the team's responsibility, not owm's. Per-instance Postgres roles would be the server-side isolation mechanism if ever needed (extension point, not local concern).

---

## Remaining CLI commands

### delete

```
owm delete feat-789 (instance running)
→ hard error: instance must be stopped first
```

```
owm delete feat-789 (stopped, no --force)
→ displays checklist: session notes path if they exist, open compare pairs, any other configured checks
→ requires explicit confirmation per item or single --force to skip all
# checklist is configurable; defaults are lightweight, not blocking
```

```
owm delete feat-789 --force
→ skips checklist; removes worktrees, DB, reverse proxy block, instance folder; no recovery
→ cleans up all workspace.toml references (compare_pairs, any other entries referencing this instance)
```

### rename

```
owm rename feat-789 pd-789
→ renames instance folder, DB, nginx block (feat-789.localhost → pd-789.localhost)
→ updates toml references; port unchanged (passed explicitly to internal create)
→ updates any _archive/ references and compare_pair entries in workspace.toml
→ updates reverse proxy block (old-name.localhost → new-name.localhost)
```

```
owm rename feat-789 pd-789 (instance running)
→ hard error: stop first
```

### logs

```
owm logs feat-789
→ last N lines (configurable default, e.g. 50); structured, level-aware
```

```
owm logs feat-789 -n 200
→ last 200 lines
```

```
owm logs feat-789 --follow
→ live tail; streams new lines as written
```

```
owm logs feat-789 --level ERROR
→ filtered to ERROR and above
# log levels supported from the start, not bolted on later
# same underlying producer consumed by CLI and dashboard — no separate log producers
```

### shell

```
owm shell feat-789
→ drops into odoo-bin shell on feat-789's instance
```

```
owm shell feat-789 < script.py
→ pipes script into shell; no need to step in interactively
```

### db-dump / db-restore

```
owm db-dump feat-789
→ dumps instance DB to _dumps/feat-789/<timestamp>.dump
→ prints path on completion
```

```
owm db-dump feat-789 --out /some/path/snapshot.dump
→ dumps to explicit path
```

```
owm db-restore feat-789 snapshot.dump
→ resolves to _dumps/feat-789/snapshot.dump if not an absolute path
→ restores DB; instance must be stopped
```

```
owm db-restore feat-789 /explicit/path/snapshot.dump
→ restores from explicit path
```

```
owm db-restore feat-789 (instance running)
→ hard error: stop instance first
```

### validate

```
owm validate feat-789
→ static validation of instance.toml: required fields, repo refs exist in workspace, port not contested, branch format valid
→ no instance materialised; safe to run on toml before create
```

```
owm validate feat-789 (instance already exists)
→ validates toml against live state: worktrees present, DB reachable, venv resolves, nginx block active
```

### init

```
owm init
→ workspace bootstrapping: bare clones from workspace.toml repo URLs, DB cluster provisioned
→ idempotent: skips what already exists
→ reverse proxy block for owm dashboard written (proxy implementation TBD: nginx vs caddy vs other)
→ local CA cert installed for *.localhost HTTPS
```

```
owm init (run again after adding new repo to workspace.toml)
→ clones new repo only; existing repos untouched
```

---

## Fetch and sync

Single source of truth: `origin`. No local remotes, no cross-workspace syncing. Anything moving between workspaces routes through origin first.

Fetch is always workspace-wide — no per-instance or per-repo fetch surface in owm. Single-repo fetch available as raw git for edge cases (expertise filter).

```
owm fetch
→ checks each bare clone for available remote updates (smart skip if nothing new)
→ fetches all repos with updates in parallel
→ fast-forwards shared worktrees to new remote state automatically
→ logs previous hash per shared worktree before fast-forward (for rollback)
→ event bus emits fetch-completed
```

```
owm fetch, one repo's remote unreachable
→ warns and continues; other repos fetched normally
→ owm.log records failure
```

```
owm fetch, shared worktree fast-forward would overwrite local commits
→ hard stop on that worktree; warn user; other worktrees proceed
# shared worktrees should never have local commits — this is the footgun signal
```

### Instance sync and push

```
owm sync feat-789
→ per repo: if purely behind origin, fast-forwards silently
→ if diverged: surfaces divergence, instructs user to rerun with --rebase
# "owm sync --rebase rebases your local commits onto origin, making it origin+your additions"
```

```
owm sync feat-789 --rebase
→ rebases local commits onto origin for diverged repos
→ result is origin+local-additions; ready to push
```

```
owm sync feat-789, repo is dirty (uncommitted changes)
→ skips that repo with clear reason; other repos proceed
```

```
owm push feat-789
→ pushes owned branches to origin
→ refused if branch is diverged (not rebased yet)
→ refused if branch is not owned (review branch, shared branch)
```

```
owm push feat-789, branch purely ahead of origin
→ fast-forward push; succeeds
```

```
owm reset feat-789
→ hard resets all worktrees to origin state
→ intended for review instances; destructive but explicit
→ warns if any worktree has local commits not on origin
```

```
user manually marks feat-789 as broken with note (health checks passing)
→ recorded as known-bad with annotation; surfaced in status and dashboard
→ informational only — does not block operations
```

### Confirmed-working checkpoints

Automatically recorded when: green script run + health check passing + module install check passing. User can also manually mark with a note (for known-broken-but-usable states).

Checkpoint captures: git hash per repo worktree + DB snapshot.

```
all checks pass on feat-789
→ checkpoint recorded: {timestamp, hashes: {repo: hash, ...}, db_snapshot: path}
→ owm.log entry
```

```
user manually marks feat-789 as confirmed-working with note
→ checkpoint recorded with note; marked as manual rather than automatic
```

```
owm rollback feat-789
→ reverts all worktrees to hashes from last confirmed-working checkpoint
→ restores DB snapshot from same checkpoint
→ surfaces which checkpoint was used and what changed since
```

```
shared worktree fast-forwarded, no confirmed-working checkpoint exists yet
→ hash logged but no DB snapshot (no DB associated with shared worktrees)
→ rollback available for the worktree only
```

```
owm fetch introduces DB migration on fast-forward
→ DB snapshot taken before fast-forward proceeds
# migration may break instance; snapshot is the safety net
```

---

## MCP surface

**Safety invariants maintained across all tools — non-negotiable, must survive any future refactor:**
- No tool touches upstream destructively — no force-push, no remote branch delete
- Push tools refuse unowned/shared branches unconditionally
- Delete/archive/reset tools operate on local state only
- These are explicit constraints, not conventions

### Workspace tools

```
owm_status()
→ full workspace status: instances, repos/worktrees, ports, unmanaged processes, alerts

owm_status(instance="feat-789")
→ feat-789 state + any unmanaged processes that look associated (port match, DB name in cmd)

owm_status(include_repos=True, include_ports=False, include_unmanaged=False)
→ selective mode: only flagged sections returned

owm_status(instance="feat-789") (not found)
→ {"error": "instance not found", "code": "NOT_FOUND"}
```

```
owm_ps()
→ {managed: [{instance, pid, port, url, status}], unmanaged: [{pid, port, cmdline}]}
# no git calls, no config parsing — instant
```

```
owm_validate(instance="feat-789")
→ static: {valid: bool, errors: [...], warnings: [...]}

owm_validate(instance="feat-789", live=True)
→ static + live checks (worktrees, DB, venv, proxy block): same shape, richer errors
```

```
owm_env(instance="feat-789")
→ {ODOO_BIN, VENV_PYTHON, PSQL, DB_NAME, DB_PORT, INSTANCE_DIR, LOG_FILE,
   HTTP_PORT, GEVENT_PORT, ODOO_CONF, WORKSPACE_DIR, SCRIPTS_DIR, WORKSPACE_SCRIPTS_DIR}
```

```
owm_audit_log(n=50)
→ {lines: [...last 50 structured owm.log entries...]}

owm_audit_log(n=100, level="ERROR")
→ last 100 ERROR-and-above entries

owm_audit_log(since="2026-05-16T08:00:00")
→ all entries since timestamp
```

### Lifecycle tools

Repo spec string format: `"branch:base+flags"` where flags are `readonly`, `exists`, `shared`.
Examples: `"feat-789-dev:dev"`, `"feat-789-dev:dev+readonly"`, `"feat-789-dev:dev+exists"`, `"19.0:shared"`

`+exists`: branch must exist upstream — fetch and check out, hard error if remote ref absent.
Without `+exists`: create locally if not found upstream.

```
owm_new(instance="feat-789", repos={"odoo": "19.0:shared", "product-core": "feat-789-dev:dev"})
→ {path: "instances/feat-789/instance.toml", content: "...toml string..."}

owm_new(instance="feat-789") (already exists)
→ {"error": "instance already exists", "code": "ALREADY_EXISTS"}
```

```
owm_create(instance="feat-789")
→ reads instance.toml from disk; materialises idempotently
→ {"status": "ok", "created": [...], "updated": [...], "skipped": [...]}

owm_create(instance="feat-789", toml="[repos]\n...")
→ uses inline toml; writes to disk as part of create; no disk round-trip needed

owm_create(instance="feat-789", repos={"product-core": "feat-789-dev:dev+exists"})
→ {"error": "branch feat-789-dev not found on origin", "code": "BRANCH_NOT_FOUND"}

owm_create(instance="feat-789") (dirty worktree on branch switch)
→ {"error": "uncommitted changes", "code": "DIRTY_WORKTREE", "repo": "product-core"}
```

```
owm_start(instance="feat-789")
→ {"status": "spawned", "pid": 1234, "url": "https://feat-789.localhost"}

owm_start(instance="feat-789", wait=True)
→ {"status": "healthy", "pid": 1234, "url": "https://feat-789.localhost"}
→ {"error": "timed out", "code": "START_TIMEOUT", "pid": 1234}

owm_start(instance="feat-789") (already running)
→ {"status": "already_running", "pid": 1234, "url": "https://feat-789.localhost"}
```

```
owm_stop(instance="feat-789")
→ {"status": "stopping", "pid": 1234}

owm_stop(instance="feat-789", wait=True)
→ {"status": "stopped"} on clean exit
→ {"status": "timeout", "code": "STOP_TIMEOUT", "pid": 1234, "hint": "call owm_kill to force"}
# never auto-kills — explicit owm_kill required

owm_stop(instance="feat-789") (not running)
→ {"status": "not_running"}
```

```
owm_kill(instance="feat-789")
→ {"status": "killed", "pid": 1234}

owm_kill(instance="feat-789") (not running)
→ {"status": "not_running"}
```

```
owm_restart(instance="feat-789", wait=False)
→ {"status": "restarted", "pid": 1235, "url": "https://feat-789.localhost"}

owm_restart(instance="feat-789") (stop timed out)
→ {"error": "stop timed out", "code": "STOP_TIMEOUT", "hint": "call owm_kill then owm_start"}
# restart never force-kills implicitly
```

```
owm_health(instance="feat-789")
→ {"status": "healthy", "pid": 1234, "http_alive": true, "url": "https://feat-789.localhost"}
→ {"status": "starting", "pid": 1234, "http_alive": false}
→ {"status": "unhealthy", "pid": 1234, "http_alive": false}
→ {"status": "stopped"}
→ {"status": "unmanaged", "pid": 1234, "port": 8142}
# process + HTTP only — DB/venv/module state is owm_validate territory
```

```
owm_archive(instance="feat-789")
→ {"status": "archived", "path": "_archive/feat-789/"}

owm_archive(instance="feat-789", discard_db=True)
owm_archive(instance="feat-789", discard_artifacts=True)

owm_archive(instance="feat-789") (running)
→ {"error": "stop instance first", "code": "INSTANCE_RUNNING"}
```

```
owm_delete(instance="feat-789", force=True)
→ {"status": "deleted"}
# force=True required for agents — skips checklist, cleans workspace.toml references

owm_delete(instance="feat-789") (running)
→ {"error": "stop instance first", "code": "INSTANCE_RUNNING"}
```

```
owm_rename(instance="feat-789", new_name="pd-789")
→ {"status": "renamed", "old": "feat-789", "new": "pd-789", "url": "https://pd-789.localhost"}

owm_rename(instance="feat-789") (running)
→ {"error": "stop instance first", "code": "INSTANCE_RUNNING"}
```

### Sync tools

```
owm_fetch()
→ {repos: {odoo: "fetched", product-core: "skipped (nothing new)", ...},
   shared_worktrees: {"odoo/19.0": "fast-forwarded", ...}}
```

```
owm_sync(instance="feat-789")
→ {repos: {
     product-core: {status: "fast-forwarded", from: "abc123", to: "def456"},
     customer-config: {status: "diverged", hint: "call owm_sync with rebase=True for this repo"},
     odoo: {status: "skipped", reason: "shared worktree"}
   }}

owm_sync(instance="feat-789", repo="customer-config", rebase=True)
→ {repos: {customer-config: {status: "rebased", from: "abc123", to: "def456"}}}

owm_sync(instance="feat-789", repo="product-core") (dirty)
→ {repos: {product-core: {status: "skipped", reason: "uncommitted changes"}}}
```

```
owm_push(instance="feat-789", repo="product-core")
→ {"status": "pushed", "repo": "product-core", "branch": "feat-789-dev"}

owm_push(instance="feat-789", all=True)
→ {repos: {product-core: {status: "pushed"}, odoo: {status: "skipped", reason: "shared"}}}

owm_push(instance="feat-789", repo="product-core") (diverged)
→ {"error": "branch diverged, rebase first", "code": "DIVERGED"}

owm_push(instance="feat-789", repo="odoo") (shared)
→ {"error": "shared worktrees not managed by owm push", "code": "SHARED_REPO",
   "hint": "git -C _shared/odoo/19.0 push origin 19.0"}

owm_push(instance="review-101", repo="product-core") (readonly)
→ {"error": "branch not configured as owned", "code": "NOT_OWNED"}
```

```
owm_reset(instance="review-101", repo="product-core")
→ {"status": "reset", "repo": "product-core", "to": "origin/feat-789-dev"}

owm_reset(instance="review-101", all=True)
→ {repos: {product-core: {status: "reset"}, odoo: {status: "skipped", reason: "shared"}}}

owm_reset(instance="review-101", repo="product-core") (dirty)
→ {"error": "uncommitted changes", "code": "DIRTY_WORKTREE",
   "hint": "call with force=True to discard"}

owm_reset(instance="review-101", repo="product-core", force=True)
→ {"status": "reset", "discarded_changes": true}
```

### Script tools

```
owm_run_script(instance="feat-789", script="run")
→ {
    status: "ok" | "fail" | "abort",
    summary: {ok: 8, fail: 1, warn: 0, none: 1, total: 10},
    failures: [{case, status, result, expected}],
    ndjson_path: "_dumps/feat-789/run-2026-05-16T09:32.ndjson"
  }
# full stdout not returned; failures only surfaced if status != "ok"

owm_run_script(instance="feat-789", script="run") (abort)
→ {status: "abort", reason: "DB connection failed", rows_run: 3, ndjson_path: "..."}
```

```
owm_get_script_failures(ndjson_path="...")
→ [{case, status, result, expected, note}, ...]
# targeted extraction when agent needs to dig into a specific run
```

```
owm_compare(instance="feat-789")
→ {
    status: "ok" | "has_changes" | "unexpected_changes" | "abort",
    summary: {identical: 7, expected_changes: 1, unexpected_changes: 1, total: 9},
    unexpected: [{case, base, feat, result_diff}],
    expected: [{case, base, feat, declared: true}],
    ndjson_base: "...", ndjson_feat: "..."
  }

owm_compare(instance="feat-789", base="main")
→ ad-hoc compare, no workspace declaration required

owm_compare(instance="feat-789") (no compare_pair configured)
→ {"error": "no compare_pair configured", "code": "NO_COMPARE_TARGET",
   "hint": "add compare_pair to workspace.toml or pass base parameter"}
```

```
owm_upgrade(instance="feat-789", modules=["my_module"])
→ {"status": "ok", "modules": ["my_module"], "restarted": true}
→ {"status": "fail", "log_tail": "...last 20 lines...", "code": "UPGRADE_FAILED"}

owm_upgrade(instance="feat-789", in_place=True, modules=["my_module"])
→ {"status": "ok", "modules": ["my_module"], "restarted": false}
→ {"error": "in_place requires workers > 0", "code": "NO_WORKERS"}
→ {"error": "xmlrpc unavailable", "code": "XMLRPC_UNAVAILABLE"}
```

### DB tools

```
owm_db_reset(instance="feat-789")
→ {"status": "ok", "restored_from": "odoo19_base_template"}

owm_db_dump(instance="feat-789")
→ {"status": "ok", "path": "_dumps/feat-789/2026-05-16T09:32.dump"}

owm_db_dump(instance="feat-789", out="/explicit/path/snapshot.dump")
→ {"status": "ok", "path": "/explicit/path/snapshot.dump"}

owm_db_restore(instance="feat-789", path="2026-05-16T09:32.dump")
→ resolves to _dumps/feat-789/2026-05-16T09:32.dump if not absolute
→ {"status": "ok"}

owm_db_restore(instance="feat-789") (running)
→ {"error": "stop instance first", "code": "INSTANCE_RUNNING"}
```

### Context tools

```
owm_logs(instance="feat-789", n=50)
→ {lines: [...structured log entries...], log_path: "/path/to/odoo.log"}

owm_logs(instance="feat-789", n=200, level="ERROR")
owm_logs(instance="feat-789", since="2026-05-16T09:00:00")
# no search/filter parameter — use LOG_FILE path from owm_env for grep
```

```
owm_agent_context(instance="feat-789", role="reviewer")
→ {
    context: "...role template + workspace boilerplate + instance notes concatenated...",
    sources: {role_template: "~/.claude/roles/reviewer.md",
              workspace: "dev-instances/CLAUDE.md",
              instance: "instances/feat-789/notes.md"}
  }

owm_agent_context(instance="feat-789") (no role)
→ workspace boilerplate + instance notes only

owm_agent_context(instance="feat-789") (no instance notes)
→ {context: "...role + workspace...", sources: {..., instance: null}}
# missing instance notes is not an error
```

---

## Session context files

Three purpose-separated files per instance, all optional. Absent = fully mechanised instance, no residual context needed.

| File | Contains | Consumed by |
|------|----------|-------------|
| `setup.md` | Non-obvious setup steps owm and scripts can't reproduce: manual steps, env quirks, external service prerequisites. **Absent is the happy path.** | Setup agents, humans recreating the instance |
| `notes.md` | Facts about the instance: architectural observations, soft constraints, reviewer context, anything worth preserving for future-you or an agent. Not a journal. | Review agents, drift-analysis agents, humans doing follow-up |
| `review/` | Dated review snapshots, one file per significant review event. Append-only, latest is canonical. | Review agents, humans re-reviewing after PR updates |

Review file naming: `YYYY-MM-DD-<trigger>.md` — trigger is `initial`, `post-rebase`, `post-update`, `re-review`.

```
instance fully mechanised (owm config + idempotent scripts cover everything)
→ setup.md absent; happy path
```

```
instance requires manual step (external service, non-standard env)
→ setup.md present with that step; owm surfaces its existence on status
```

```
review event occurs (first pass, post-rebase, etc.)
→ new file written to review/; previous files retained as history
→ latest file is canonical current assessment
```

```
agent writes blind review
→ writes to review/YYYY-MM-DD-initial.md (or appropriate trigger)
→ never overwrites existing files — always appends a new dated file
```

```
owm_agent_context consumes instance notes
→ reads notes.md + latest review/ file; setup.md included if present
→ review/ history not included (too much noise); agent can request specific file if needed
```

**Personal session journal** (`~/notes/sessions/<project>/<date>.md`): developer's working log — what got done, what's next, what blocked. Separate from instance files in intent. Instance `notes.md` is facts about the instance; session journal is the developer's stream of consciousness. Non-owm projects and project-wide concerns go in `~/notes/sessions/` directly rather than in any instance dir.

---

## Deferred / to verify

The following areas were implied by the spec but not fully elaborated. Revisit when writing red tests — use this as a checklist to catch gaps before they become implementation surprises.

- [ ] **workspace.toml schema** — full field list: repos, clusters, defaults (port range, sync_warn_hours, worker count), patches, compare_pairs, workspace_scripts_dir, proxy config
- [ ] **instance.toml schema** — full field list: repos (branch/base/shared/readonly/exists flags), database, server (http_port, workers), install (modules), python (version), scripts (runners, compare_target), session context paths
- [ ] **owm ps (CLI)** — specced as MCP only; needs CLI cases
- [ ] **Template DB management** — `owm template-refresh` command; how base template is updated, which modules are pre-installed, how staleness is tracked and surfaced
- [ ] **owm rollback (CLI + MCP)** — concept specced in fetch/sync section; CLI and MCP surface not elaborated
- [ ] **owm adopt (MCP)** — CLI specced; MCP tool not listed
- [ ] **owm-server extension points** — flagged throughout; worth a consolidated section before any server work begins
- [ ] **Proxy block lifecycle** — what happens to proxy blocks on delete/archive/rename if proxy process is not running; who owns blocks owm didn't create
- [ ] **Worker count research** — default 2 noted as unverified; check Odoo docs for memory-per-worker and recommended counts before finalising
- [ ] **Log rotation configuration** — 20k lines / 1 week noted as initial proxies; verify these are sensible defaults
- [ ] **compare_pair in workspace.toml** — declared as symmetric pair; behaviour when one instance is archived but pair entry not cleaned up
- [ ] **owm new-script scaffolding** — contract-level template format not fully specced
- [ ] **Plugin/external service contract** — up/down/status/reset interface noted; full contract not elaborated

---

## Technology recommendation

**Python throughout.**

Static argument: core Odoo is Python. Rewriting osh, pr-ism, and existing owm is possible but carries cost; Odoo itself being Python is the load-bearing constraint.

Ecosystem fit: shell/toolchain integration (uv, git, psql, odoo-bin as subprocesses), FastAPI for the dashboard and MCP server, TOML parsing, process management — all well-trodden Python territory. No performance or memory safety requirements that Python can't meet. Docker deployment removes "already installed" as a platform concern.

**Pydantic for config schemas** — workspace.toml and instance.toml parsing are the places where strict typing pays off most. Making invalid config states unrepresentable catches a class of bugs (missing required fields, wrong types, contested ports) at parse time rather than at materialisation time. Worth the dependency.

**Vanilla JS + SSE for dashboard** — no build toolchain, no framework. Explicit call from the spec. Holds.

**Future trigger for reconsidering:** if the NDJSON/behavioral contract protocol is extracted as a standalone library (noted in osh DESIGN.md and refactoring-workflow notes), that extraction point is where algebraic types would genuinely reward a stricter type system. Not now — extract first, reconsider at that boundary.

---

## Database auth

### Local model (fully specced)

Unix socket + peer auth. owm runs as the operator Unix user; that user has a Postgres superuser role on each cluster. No passwords, no credential management. All DBs owned by the operator user directly.

```
owm create feat-789
→ DB created/cloned under operator's Postgres role; no password required
→ connection: unix socket at /var/run/postgresql/<port>
```

```
owm shell feat-789 (DB connection from odoo-bin shell)
→ connects via unix socket as operator user; peer auth passes automatically
```

```
script run requiring DB access
→ same peer auth; no credential passing required in script
```

```
pg_isready -h /var/run/postgresql -p <port>
→ sufficient reachability check; owm uses this for DB health
```

```
owm init
→ creates operator Postgres superuser role if absent (createuser --superuser $(whoami))
→ one-time per cluster; idempotent
```

**dbfilter**: set in generated `instance.conf` to match the instance subdomain (e.g. `dbfilter = ^feat-789$`). Safe and beneficial with the subdomain model — each instance has its own hostname so no cross-instance cookie/session bleed. Prevents DB switching via URL manipulation.

**Reversal from existing owm DESIGN.md:** the existing DESIGN.md explicitly says *don't* set dbfilter for local dev instances. That decision was made in the port-based model where all instances shared `localhost` as the host header — dbfilter would have caused silent logouts when switching between ports. With the subdomain model each instance has a distinct hostname, so the original concern no longer applies. This is an intentional design change, not an oversight.

**Superuser**: local model uses operator superuser role for convenience (peer auth, single user, no credential management). Odoo docs recommend non-superuser for production — extension point for owm-server.

**Local model assumptions (extension points for owm-server):**
- Single operator user owns all DBs — *server: per-instance roles, isolated ownership, non-superuser*
- Unix socket transport — *server: TCP with scram-sha-256 (18.0+) or md5 (12/14), credentials in ~/.pgpass or secrets manager, never in config files*
- Peer auth (OS user = Postgres role) — *server: explicit auth, per-user credentials*
- Single machine, co-located Postgres — *server: remote Postgres, connection string in workspace config*
- No network exposure — *server: pg_hba.conf revisited per cluster, TLS on Postgres connections*

No per-instance Postgres roles locally — they add ceremony without meaningful isolation on a single-user machine. Server model revisits from scratch rather than extending the local model.

---

## Archive

```
owm archive feat-789
→ preserves by default: instance.toml, DB dump, session markdown, review snapshots
→ DB dumped to _archive/feat-789/db.dump before removal
→ removes worktrees, drops live DB; frees port back to pool
→ stored in _archive/feat-789/
```

```
owm archive feat-789 --discard-db
→ preserves toml and session artifacts; skips DB dump, drops live DB
```

```
owm archive feat-789 --discard-artifacts
→ preserves toml only; discards DB and session markdown
```

```
owm archive feat-789 (instance is running)
→ hard error: stop the instance first
```

```
owm create pd-123 (pd-123 exists in _archive/)
→ human: prompts "found archived instance from <date> — restore or start fresh?"
→ agent: hard error unless --restore or --fresh flag provided
# date surfaced so recycled ticket names are immediately obvious
```

```
owm create pd-123 --restore
→ restores from archive: worktrees recreated, DB restored if archived, port reassigned (fresh port, not original)
```

```
owm create pd-123 --fresh
→ renames archive to pd-123_archived_2026-01-15 before creating new instance
→ old archive preserved, nothing silently overwritten
```

```
owm archive-delete pd-123
→ permanently removes _archive/pd-123/; requires explicit confirmation
```

```
owm archive-delete pd-123_archived_2026-01-15
→ cleans up a timestamped archive from a --fresh create
```

---

## CWD inference

All commands walk up from cwd to find workspace.toml (workspace root). Instance-scoped commands additionally infer the target instance if cwd is inside `instances/<name>/`. Applies to: status, start, stop, kill, restart, health, logs, run-script, compare, sync, push, reset, upgrade, shell, env, db-dump, db-restore, db-reset, archive, delete, rename, validate.

Explicit instance name always overrides cwd inference.

```
cwd = ~/dev-instances/instances/feat-789/product-core/
owm status
→ infers feat-789; returns status for feat-789 only
```

```
cwd = ~/dev-instances/
owm status
→ no instance inferred; returns workspace-wide status
```

```
cwd = ~/dev-instances/instances/feat-789/
owm status review-101
→ explicit name overrides cwd; returns status for review-101
```

---

## Unmanaged processes and adoption

```
owm status (workspace-wide)
→ surfaces unmanaged Odoo processes: PID, port, command line, whether port matches a configured instance
```

```
unmanaged process on port 8142, instance feat-789 configured on port 8142
→ status shows: "feat-789: unmanaged process on configured port — adopt or kill?"
```

```
owm adopt feat-789
→ links running process to feat-789 instance state (writes PID to instance state file)
→ instance now manageable via owm stop/kill/health/logs
```

```
owm adopt feat-789 (process port doesn't match configured port)
→ warns: "process is on port X, feat-789 configured for port Y — adopt anyway?"
→ requires --force to proceed
```

```
unmanaged process with no matching configured instance
→ status shows: "unmanaged Odoo process: PID X, port Y — not associated with any instance"
→ no adopt available; user handles manually
```

---

## Event bus

Separate concern from the dashboard UI. Emits structured events when instance state changes. Consumers: dashboard, MCP agent tools, --wait flags, anything that needs to react to state changes. Transport-agnostic; independently testable.

Events include at minimum: instance started, instance healthy, instance stopped, health check failed, script run completed, port eviction occurred.

---

## Script runner

Three tiers:
- **Instance-scoped**: defined in `instance.toml`, idempotent, live alongside instance config. Primary dashboard surface.
- **Workspace-scoped**: shared utilities in a central location, callable from any instance.
- **Plugin/external services**: arbitrary processes (Flask, SQL DB, Go/Rust binary etc.) conforming to a defined contract (`up/down/status/reset` subcommands, exit 0 on success, single status line to stdout). owm surfaces their status but doesn't care about internals.

Script result format: NDJSON — one JSON object per row with at minimum `{case, status}`. Status values: OK/FAIL/WARN/NONE.

### Failure handling

**Distinction from `expected_changes`:** contract-level failure handling is *intra-script* — "this specific row is allowed to fail on every run." `expected_changes` at the compare pair level is *inter-run* — "this case is allowed to differ between base and feat branches." Both are load-bearing; they operate at different axes. A script can have contract-level acceptable failures (always FAIL) that are also declared in `expected_changes` (FAIL on base, OK on feat after fix).

Three levels, opt-in from simple to full:

**Row-level** (default fallback): each NDJSON row is independent — a FAIL on row 3 doesn't abort rows 4–10. Runner collects all results and surfaces summary. Valid for quick scripts that don't need precise failure handling.

**Script-level abort**: script emits a structured abort signal (special row or exit code) meaning "core assumption failed, remaining rows are meaningless." Runner stops early and surfaces the blocker explicitly.
```
script emits abort signal (e.g. DB connection failed at setup)
→ runner stops, surfaces "core assumption failed: <reason>", remaining rows not run
```

**Contract-level** (happy path, scaffolded by `owm new-script`): script declares upfront which failure modes are acceptable vs. blocking. Runner enforces the contract.
```
script declares: FAIL on "missing_optional_field" is acceptable, FAIL on "db_write" is a blocker
→ runner continues on acceptable failures, hard-stops on blockers
→ dashboard surfaces contract violations distinctly from expected failures
```

```
owm new-script feat-789 setup
→ scaffolds contract-level script template with contract declaration section
# gentle pressure toward contract-level; row-level always valid as escape hatch
```

### Compare pairs

Declared in `workspace.toml` as `compare_pair = ["feat-789", "main"]`. Symmetric means neither instance is designated primary in the declaration — either instance can initiate the compare invocation (`owm compare feat-789` or `owm compare main` are both valid and produce the same diff, just from different perspectives). Dashboard groups them visually as a pair with no directional arrow.

```
owm compare feat-789
→ resolves compare_target from workspace.toml; runs script on both instances; diffs NDJSON output
→ expected_changes declaration on the pair is the reviewable artifact
```

```
owm compare feat-789 --against main
→ ad-hoc compare, no workspace declaration required
```

```
owm compare feat-789, runner flag --parallel
→ both instances run script simultaneously; valid if scripts have no shared external state
```

```
owm compare feat-789, runner flag --sequential
→ base runs first, then feat; use when scripts share external state that would conflict
```

```
compare pair declared in workspace.toml, one instance deleted
→ owm status surfaces: "compare pair feat-789/main: main not found"
# never silently ignored
```

```
compare script with expected_changes declared:
  main:   (OK, OK, EXCEPTION, ERROR, EXCEPTION, OK, OK)
  feat-789: (OK, OK, ERROR,     ERROR, EXCEPTION, OK, OK)
→ row 3 change (EXCEPTION→ERROR) matches declared expected_change: pass
→ all other rows identical: pass
→ any row differing outside expected_changes declaration: contract violation, surfaced explicitly
```

```
script run, all rows OK
→ dashboard shows green; NDJSON written for compare
```

```
script run, some FAIL rows, within acceptable contract range
→ dashboard shows partial; NDJSON written; no alert
```

```
script run, FAIL row outside acceptable contract range
→ dashboard surfaces contract violation; event bus emits script-failed event
```

```
script run, abort signal emitted
→ runner stops early; dashboard surfaces blocker reason; event bus emits script-aborted event
```

---

## Dashboard

Layout:
- **Header**: service-wide health, alerts (port range pressure, stale template warnings), global log toggle, owm-wide actions
- **Left pane (~400px)**: repos/worktrees card (workspace-level sync state); instances card (name, URL, running state, health — clickable); ports card (owm ps equivalent — optional but low cost)
- **Right pane (main real estate)**: selected instance — operational state, config/worktree details, ahead/behind triplet per repo, actions (start/stop/kill, run configured scripts, archive), session context markdown (read-only), logs as toggleable card

Happy-path actions exposed from UI: start, stop, force-kill, run configured scripts, view logs, archive. Anything requiring arbitrary input or config changes stays in terminal or agent.

Instance logs: per-instance toggleable card in right pane. Not pinned by default.

```
user clicks instance in left pane
→ right pane loads that instance's operational state, config, worktree details, session context
```

```
user opens log card for feat-789
→ live tail of feat-789 odoo server log, last N lines, streaming
```

```
user clicks "run setup" on feat-789
→ executes instance-scoped setup script; progress and result surfaced in right pane
```

```
dashboard opened with no instance selected
→ right pane shows workspace summary or is empty; left pane populated
```

---

## owm.log — audit trail

First-class artifact, not a dashboard nicety. Structured, append-only, written by owm regardless of whether dashboard is open. Captures owm operations: commands run (CLI or UI), agent instructions, script run completions, port evictions, template sync attempts.

Not Odoo server logs — those are per-instance. owm.log is "what owm itself did."

```
owm start feat-789
→ appends structured entry to owm.log: {timestamp, operation: "start", instance: "feat-789", result: "spawned", pid: 1234}
```

```
script run completes
→ appends entry: {timestamp, operation: "run-script", instance, script, result: ok/fail/abort, summary}
```

```
dashboard global log surface opened
→ streams owm.log tail; survives page reload (reads from file, not JS state)
```

```
owm.log tailed directly from CLI
→ works independently of dashboard; standard append-only log file
```

---

## Instance lifecycle — start/stop

```
owm start feat-789
→ odoo-bin spawned, returns immediately with PID
→ event bus emits "instance starting"
→ event bus emits "instance healthy" once HTTP responds and modules confirmed
```

```
owm start feat-789 --wait
→ blocks until healthy or timeout; exits 0 on healthy, 1 on timeout/failure
# convenience for scripts and humans watching a potentially broken start
```

```
owm health feat-789
→ returns current health state: running/starting/unhealthy/stopped
# explicit pull-based check; works independently of event bus
```

```
owm start feat-789  (already running)
→ no-op with clear message: "feat-789 is already running"
```

```
owm stop feat-789
→ graceful shutdown signal sent; returns immediately
→ event bus emits "instance stopped" when process exits
```

```
owm stop feat-789 --wait
→ blocks until process exits
```

```
owm stop feat-789  (not running)
→ no-op with clear message
```

---

## Error taxonomy

All MCP tools return errors in the form `{"error": "<message>", "code": "<CODE>"}`. Consistent codes across all tools:

| Code | Meaning |
|------|---------|
| `NOT_FOUND` | Named instance, repo, script, or archive does not exist |
| `ALREADY_EXISTS` | Instance or resource already exists (use create/owm_create for idempotent path) |
| `INSTANCE_RUNNING` | Operation requires instance to be stopped first |
| `DIRTY_WORKTREE` | Uncommitted changes prevent the operation; use `force=True` to override where applicable |
| `BRANCH_NOT_FOUND` | Branch with `+exists` flag not found on origin |
| `NOT_OWNED` | Push/write operation refused — branch not configured as owned |
| `SHARED_REPO` | Operation not applicable to shared worktrees |
| `DIVERGED` | Branch has diverged from origin; rebase required before push |
| `NO_COMPARE_TARGET` | No compare_pair declared and no base parameter provided |
| `START_TIMEOUT` | Instance did not become healthy within timeout |
| `STOP_TIMEOUT` | Instance did not stop within grace period; use owm_kill |
| `DB_UNAVAILABLE` | Postgres cluster unreachable |
| `UPGRADE_FAILED` | odoo-bin -u exited non-zero; log_tail included in response |
| `XMLRPC_UNAVAILABLE` | In-place upgrade requires running instance with workers > 0 |
| `NO_WORKERS` | Operation requires workers > 0 (gevent/longpolling) |
| `PORT_EXHAUSTED` | No free ports in configured range |
| `PORT_CONTESTED` | Pinned port held by running instance; cannot evict |

---

## Config schemas

### workspace.toml

```toml
[repos]
# repo-name = "git@..."  — SSH URLs required
odoo            = "git@github.com:odoo/odoo.git"
product-core    = "git@bitbucket.org:org/product-core.git"
customer-config = "git@bitbucket.org:org/customer-config.git"
scripts         = "git@bitbucket.org:org/scripts.git"

[repos.meta]
# has_addons = true on repos that contribute Odoo modules
# repos without has_addons are excluded from addons_path
odoo.has_addons            = true
product-core.has_addons    = true
customer-config.has_addons = true
scripts.has_addons         = false   # scripts repo: no addons

[clusters]
# keyed by Odoo major version string
"19" = {pg_version = "16", port = 5432}
"12" = {pg_version = "12", port = 5433}

[defaults]
instances_dir       = "instances"
http_port_range     = [8100, 8299]   # instance HTTP+gevent pairs
owm_port_range      = [8090, 8099]   # dashboard, metrics etc
workers             = 2              # default gevent workers per instance
sync_warn_hours     = 72             # flag repos not fetched in N hours
eviction_threshold  = 10             # port evictions per rolling week before alert
template_warn_days  = 30             # days before staleness warning on template DB

[patches]
# applied at venv install time, per Odoo version string
"19" = ["requirements_patches/odoo19_fix.txt"]
"12" = ["requirements_patches/odoo12_compat.txt"]

[compare_pairs]
# symmetric — either instance can initiate
pairs = [["feat-789", "main"], ["review-101", "main"]]

[scripts]
# workspace-scoped scripts callable from any instance
scripts_dir = "scripts/workspace"

[proxy]
# implementation TBD (nginx vs caddy); subdomain model is the interface
domain_suffix = "localhost"   # instances at <name>.localhost
```

### instance.toml

```toml
[repos]
# plain string = "branch:base+flags"
# flags: shared, readonly, exists
odoo            = "19.0:shared"                        # shared worktree, no per-instance checkout
product-core    = "feat-789-dev:dev"                   # owned branch, base is dev
customer-config = "feat-789-dev:dev+exists"            # must exist upstream
scripts         = "reviews/feat-789:dev+readonly"      # review branch, push disallowed

[database]
name     = "odoo19_feat789"
pg_port  = 5432                  # references cluster in workspace.toml
template = "odoo19_base"         # optional; omit to use blank slate

[server]
http_port    = 8142
gevent_port  = 8143              # always http_port + 1
workers      = 2                 # overrides workspace default

[install]
modules = ["my_module", "other_module"]   # installed/checked on create and start

[python]
version = "3.12"                 # optional; inferred from Odoo branch if absent

[scripts]
default     = "run"              # script used when no name given to owm run-script
scripts_dir = "scripts/reviews/PD-789"   # base dir for name resolution

[scripts.runners]
setup   = {file = "setup.py",   type = "shell"}   # runs inside odoo-bin shell
run     = {file = "run.py",     type = "shell"}
compare = {file = "compare.py", type = "plain"}   # plain Python, no Odoo shell

[scripts.compare]
target = "main"                  # default compare partner; overrides workspace compare_pairs

[template]
sync_opt_in = false              # opt in to automatic template sync on fetch
```

---

## osh and the behavioral contract protocol

osh owns the OK/FAIL/WARN/NONE output protocol and the NDJSON format. Its `ndjson_utils.py` has no Odoo dependency — re-owm will be its first non-Odoo consumer.

This is the stated trigger for extracting `ndjson_utils.py` into a standalone behavioral contract library (noted in osh DESIGN.md and refactoring-workflow notes). The extraction should be driven by the test-writing phase: if re-owm's test harness consumes osh's protocol cleanly, that validates the API; if it requires changes, make them in osh first before extracting.

The three-tier failure model in this spec (row-level / script-abort / contract-level) exceeds what osh currently formalises. The test-writing phase will either validate it or discover it simplifies down — either outcome is useful signal about whether the extraction surface is right.

