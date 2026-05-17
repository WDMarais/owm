# Architecture

> Signed-off artifact for implementation-writer. Do not modify during implementation
> unless a deferred concern surfaces as a real blocker — flag to user first.

---

## Glossary

Stable terms used throughout owm. Reference here to avoid ambiguity.

| Term | Meaning |
|---|---|
| `workspace.toml` | Workspace-level config: repos, clusters, defaults, patches |
| `instance.toml` | Per-instance static config: repos/branches, DB, server ports, scripts |
| `instance.conf` | Generated Odoo runtime config (ini format) written by owm during create/start |
| `state.json` | Per-instance runtime state written by owm: status, pid, http_port, started_at |
| `owm.log` | Workspace-level audit trail (NDJSON per line); append-only |
| `instance.log` | Odoo process stdout/stderr; raw text |
| bare repo | `_repos/<name>.git` — git bare clone, source of truth for all worktrees |
| shared worktree | `_shared/<repo>/<branch>/` — single checkout shared across all instances |
| per-instance worktree | `instances/<name>/<repo>/` — owned by one instance |
| port pair | `[http_port, http_port+1]` — consecutive pair; N is HTTP, N+1 is gevent |
| stamp | Hash of requirements files + patch files; gates venv re-sync |
| `setup.md` | Environment onboarding for this instance: auth steps, first-run commands, external deps. Agent reads at session start. Intent: mechanisable over time — structured enough that a future agent could execute it, not just read it. |
| `context.md` | Curated stable anchor for agent context: PR-wide invariants, notable divergences from standard setup, open review points that persist across cycles. Written/maintained by the developer. Always included in `build_agent_context` output. Distinct from personal notes and from point-in-time review snapshots. |
| `notes.md` | Freeform personal log: raw ticket notes, evolving thoughts, scratch. Human-only; not included in agent context by default. |
| `review/` | Append-only dated Markdown snapshots from any participant (agent reviews, received feedback, pr-ism syncs). Each snapshot is point-in-time; relies on `context.md` for stable PR-wide background. Default agent context includes latest snapshot only. |

---

## On-disk state contract

```
<workspace_root>/
  workspace.toml
  owm.log                        — NDJSON audit trail
  _repos/
    <name>.git/                  — bare clone per repo
  _shared/
    <repo>/<branch>/             — shared worktrees
  _dumps/
    <instance>/
      YYYY-MM-DDTHHMM.dump       — pg_dump files
  _archive/
    <instance>/                  — archived instance (or <instance>_archived_YYYY-MM-DD/)
      instance.toml
      db.dump
      notes.md
      review/
  instances/
    <name>/
      instance.toml              — static config (read-only at runtime)
      state.json                 — {status, pid, http_port, started_at, ...}
      instance.log               — odoo-bin stdout/stderr
      instance.conf              — generated Odoo runtime config (written by owm create)
      setup.md                   — optional: environment onboarding; intent: mechanisable
      context.md                 — optional: curated PR-wide anchor (invariants, divergences, open points)
      notes.md                   — optional: freeform personal log; not agent-read by default
      review/                    — append-only dated snapshots; rely on context.md for background
        YYYY-MM-DD-<trigger>.md
      .venv/                     — per-instance virtualenv
      <repo-name>/               — per-instance worktrees
```

**`state.json` shape:**
```json
{"status": "running|stopped|starting|unhealthy|unmanaged", "pid": 1234, "http_port": 8142, "started_at": "ISO8601"}
```
Written by owm on start/stop/adopt/kill. Read by `owm_ps`, `health_check`, `owm_status`. Absent = stopped.

**`review/` semantics:** Dated Markdown snapshots from any participant — agent-written reviews,
received human feedback, pr-ism syncs, discussion notes. Each snapshot is point-in-time and
self-contained relative to `context.md` (which holds the stable PR-wide background). Trigger
label distinguishes type (`initial`, `post-rebase`, `received-feedback`, `pr-ism-sync`,
`discussion`). Append-only; never overwritten. Name collision: append `-2`, `-3` suffix.

**Agent context bundle (default):** `setup.md` (if present) + `context.md` (if present) +
latest `review/` snapshot (if any). `notes.md` excluded by default — personal log, not curated
for agents. `review_include` parameter controls how many snapshots to include: `"latest"`
(default), `"all"`, or `N: int` (past N). Non-default values raise `NotImplementedError` until
implemented.

---

## Resolved conventions (implementation-trivial spec gaps)

| Convention | Resolution |
|---|---|
| `owm.log` format | NDJSON per line: `{timestamp, level, operation, instance, result, pid?, source?, summary?}` |
| DB dump naming | `_dumps/<instance>/YYYY-MM-DDTHHMM.dump` |
| `instance.conf` location | `instances/<name>/instance.conf` |
| Port pair | `[N, N+1]`; N = http, N+1 = gevent; skip whole pair if either occupied |
| Port range boundary | `[8100, 8299]` = 100 pairs; 8298 = last valid HTTP, 8299 = last valid gevent |
| `simulate_*` parameters | Kept as real injection parameters in production signatures; provide controlled state without disk/process setup |
| `addons_paths` ordering | **Declaration order is priority order throughout** — first-declared = highest priority, same rule for repos and for `addons_paths` within a repo. Declare `customer-config` before `odoo`. Optional `defaults.repo_priority` list overrides declaration order explicitly. Diverges from owm, which reversed inter-repo order. |

---

## Module layout

```
src/owm/
  __init__.py
  errors.py          — error codes (constants) + format_error
  config.py          — parse_workspace_config, parse_instance_config, parse_repo_spec + types
  audit_log.py       — append_log_entry, read_log_tail, parse_log_entry
  log_rotation.py    — check_rotation_needed, rotate_log
  session_context.py — get_context_files, write_review_snapshot, build_agent_context
  ports.py           — assign_port, honour_pinned_port, check_port_at_start, evict_port
  addons.py          — resolve_addons_path
  env.py             — resolve_env, format_env
  worktrees.py       — resolve_worktree_path, create_worktree, push_branch
  database.py        — create_db, reset_db, sync_db_from_template, check_template_staleness
  venv.py            — create_venv, sync_venv_if_needed, rebuild_venv, compute_stamp
  sync.py            — fetch_workspace, sync_instance, push_instance, reset_instance
  workspace.py       — init_workspace
  instance.py        — new_instance, create_instance, start_instance, stop_instance, kill_instance,
                        restart_instance, health_check, generate_instance_conf
  modules.py         — install_modules, upgrade_modules, check_modules_present
  scripts.py         — run_script, parse_ndjson_output, compare_instances, scaffold_script
  archive.py         — archive_instance, create_from_archive, delete_archive, detect_archive_conflict
  adoption.py        — detect_unmanaged_processes, adopt_process, status_with_unmanaged
  cli.py             — delete_instance, rename_instance, show_logs, db_dump, db_restore,
                        validate_instance, adopt_instance, infer_instance_from_cwd
  mcp.py             — all owm_* MCP tools (25 tools)
```

---

## Shared types

Types asserted identically across multiple test files — owned by the module listed.

| Type | Fields | Owner | Used by |
|---|---|---|---|
| `ErrorResponse` | `{error: str, code: str, hint?: str, repo?: str, log_tail?: str}` | `owm.errors` | all modules |
| `RepoSpec` | `{branch, base, shared, readonly, exists}` (all bool/str) | `owm.config` | config, worktrees, addons, sync |
| `PortPair` | `{http_port: int, gevent_port: int}` | `owm.ports` | ports, instance, archive |
| `PortConflict` | `{instance?, running?, requires_confirmation?, pid?, name?, cmdline?, options?}` | `owm.ports` | ports |
| `ScriptSummary` | `{ok, fail, warn, none, total: int}` | `owm.scripts` | scripts, mcp |
| `HealthResult` | `{status, pid?, http_alive?, url?, port?, unmanaged?}` | `owm.instance` | instance, mcp |
| `EventEmission` | `events_emitted: list[str]` pattern | `owm.instance` | instance, sync (for SSE/dashboard) |

`OwmError` (exception class) lives in `owm.errors`. All raise sites raise `OwmError(message, code=CODE)`.

---

## Implementation order (DAG)

```
1.  owm.errors          — leaf; pure constants + format_error; 2 tests already green
2.  owm.config          — leaf; high-fanout (17/20 modules import it); implement first
3.  owm.audit_log       — leaf; no owm deps; NDJSON append-only log
4.  owm.log_rotation    — depends on audit_log only
5.  owm.session_context — leaf; pure filesystem; no owm deps
6.  owm.ports           — depends on errors
7.  owm.addons          — depends on config
8.  owm.env             — depends on config
9.  owm.worktrees       — depends on config + errors
10. owm.database        — depends on config + errors
11. owm.venv            — depends on config + worktrees (for paths)
12. owm.sync            — depends on config + worktrees + errors
13. owm.workspace       — depends on config + database + worktrees
14. owm.instance        — depends on config + ports + worktrees + venv + database + audit_log + errors + addons
15. owm.modules         — depends on instance
16. owm.scripts         — depends on instance + config
17. owm.archive         — depends on instance + database + ports
18. owm.adoption        — depends on instance + ports
19. owm.cli             — terminal; depends on most of the above
20. owm.mcp             — terminal; thin surface over cli/instance/scripts/sync/etc.
```

`owm.config` is the high-fanout priority — go green here before touching anything else.
`owm.errors` has 2 permanently-green tests that must stay green throughout.

---

## Per-module interface

### owm.errors

```python
# Constants — uppercase strings
NOT_FOUND, ALREADY_EXISTS, INSTANCE_RUNNING, DIRTY_WORKTREE,
BRANCH_NOT_FOUND, NOT_OWNED, SHARED_REPO, DIVERGED,
NO_COMPARE_TARGET, START_TIMEOUT, STOP_TIMEOUT,
DB_UNAVAILABLE, UPGRADE_FAILED, XMLRPC_UNAVAILABLE,
NO_WORKERS, PORT_EXHAUSTED, PORT_CONTESTED,
ARCHIVE_CONFLICT, CONFIRMATION_REQUIRED

class OwmError(Exception):
    def __init__(self, message: str, code: str, **extra): ...

def format_error(message: str, code: str, **extra) -> dict:
    # Returns {"error": message, "code": code, **extra}
```

Error code semantics (MCP consumer reference):

| Code | Trigger | Consumer action |
|------|---------|----------------|
| `NOT_FOUND` | Named instance, repo, script, or archive does not exist. | Surface to user; do not retry. |
| `ALREADY_EXISTS` | Instance or resource already exists. | Use `owm_create` for the idempotent path, or choose a different name. |
| `INSTANCE_RUNNING` | Operation requires the instance to be stopped first. | Call `owm_stop` or `owm_kill`, then retry. |
| `DIRTY_WORKTREE` | Uncommitted changes block the operation. | Surface to user; re-call with `force=True` where supported. |
| `BRANCH_NOT_FOUND` | Branch declared with `+exists` flag not found on origin. | Verify branch name or remove `+exists` flag. |
| `NOT_OWNED` | Push/write refused — branch not configured as owned. | Do not retry; surface to user. |
| `SHARED_REPO` | Operation not applicable to shared worktrees. | Do not retry; surface to user. |
| `DIVERGED` | Branch has diverged from origin; rebase required before push. | Call `owm_sync` to rebase, then retry push. |
| `NO_COMPARE_TARGET` | No compare_pair declared and no `base` parameter provided. | Re-call with an explicit `base` argument. |
| `START_TIMEOUT` | Instance did not become healthy within timeout. | Check logs via `owm_logs`; surface to user. |
| `STOP_TIMEOUT` | Instance did not stop within grace period. | Call `owm_kill` to force-terminate. |
| `DB_UNAVAILABLE` | Postgres cluster unreachable. | Verify cluster is running; surface to user. |
| `UPGRADE_FAILED` | `odoo-bin -u` exited non-zero; `log_tail` included in response. | Surface `log_tail` to user for diagnosis. |
| `XMLRPC_UNAVAILABLE` | In-place upgrade requires a running instance with `workers > 0`. | Start the instance with workers, then retry. |
| `NO_WORKERS` | Operation requires `workers > 0` (gevent/longpolling). | Reconfigure instance with workers > 0. |
| `PORT_EXHAUSTED` | No free ports in configured range. | Evict stale instances or widen port range in `workspace.toml`. |
| `PORT_CONTESTED` | Pinned port held by a running instance; cannot evict. | Stop the conflicting instance or change the pinned port. |
| `ARCHIVE_CONFLICT` | `owm_new` called when `_archive/<name>/` exists and no resolution flag provided (agent mode). | Re-call with `flag="restore"` to restore from archive, or `flag="fresh"` to rename the archive and create fresh. |
| `CONFIRMATION_REQUIRED` | `owm_archive` delete path invoked without `confirmed=True`. Destructive/irreversible operation gate. | Re-call with `confirmed=True` after surfacing confirmation to the user. |

Spec gaps: `DB_UNAVAILABLE` trigger not shown for any specific tool call.

---

### owm.config

```python
# Types
@dataclass
class RepoSpec:
    branch: str
    base: str | None
    shared: bool
    readonly: bool
    exists: bool

@dataclass
class RepoMeta:
    has_addons: bool
    addons_paths: list[str]  # default: ["."]

@dataclass
class ClusterConfig:
    pg_version: str
    port: int

@dataclass
class WorkspaceDefaults:
    instances_dir: str          # default: "instances"
    http_port_range: list[int]  # default: [8100, 8299]
    owm_port_range: list[int]   # default: [8090, 8099]
    workers: int                # default: 2
    sync_warn_hours: int        # default: 72
    eviction_threshold: int     # default: 10
    template_warn_days: int     # default: 30

@dataclass
class WorkspaceConfig:
    repos: dict[str, str]           # name → git-url
    repos_meta: dict[str, RepoMeta]
    clusters: dict[str, ClusterConfig]
    defaults: WorkspaceDefaults
    patches: dict[str, list[str]]   # odoo-version → patch files
    compare_pairs: list[list[str]]
    proxy: ProxyConfig | None
    scripts: WorkspaceScripts | None

@dataclass
class InstanceConfig:
    repos: dict[str, RepoSpec]
    database: DatabaseSection
    server: ServerSection       # {http_port, gevent_port, workers}
    install: InstallSection | None
    python: PythonSection | None
    scripts: InstanceScripts | None
    template: TemplateSection | None

# Functions
def parse_workspace_config(toml: str) -> WorkspaceConfig: ...
def parse_instance_config(toml: str) -> InstanceConfig: ...
    # Validates gevent_port == http_port + 1; raises OwmError otherwise
def parse_repo_spec(spec: str) -> RepoSpec: ...
    # Parses "branch:base+flags" format
```

Spec gaps:
- Empty `[repos]` table — hard error or not? (doesn't block module; default to hard error)
- `addons_paths` default `["."]` — confirmed convention (surfaced during harness-writer)
- Version string normalisation for patches ("19" vs "19.0") — treat as literal key match

---

### owm.audit_log

```python
def append_log_entry(log_path: str, operation: str, instance: str, result: str,
                     *, pid: int | None = None, source: str | None = None,
                     summary: dict | None = None, script: str | None = None,
                     dashboard_open: bool = True) -> dict:
    # Appends NDJSON entry; returns the entry dict

def read_log_tail(log_path: str, n: int, *,
                  simulated_line_count: int | None = None) -> list[dict]: ...

def parse_log_entry(raw: str) -> dict: ...
```

Spec gaps: eviction entry shape; template sync entry shape (format matches general pattern above).

---

### owm.log_rotation

```python
def check_rotation_needed(line_count: int, log_age_days: int,
                           threshold_lines: int, threshold_days: int) -> RotationCheck:
    # Returns {needed: bool, reason: str}

def rotate_log(log_path: str, mode: str) -> RotationResult:
    # mode="local": discard; returns {discarded: bool, summarised: bool}
```

---

### owm.session_context

```python
def get_context_files(instance_dir: str, *,
                      files_present: list[str] | None = None) -> ContextFiles:
    # Returns {setup_md, context_md, notes_md, review_snapshots, latest_review, happy_path}
    # context_md = content/path of context.md (stable PR anchor); notes_md = personal log

def write_review_snapshot(instance: str, instance_dir: str, trigger: str,
                           date: str, content: str, *,
                           existing_files: list[str] | None = None) -> SnapshotResult:
    # Never overwrites; collision → suffix -2, -3. Returns {path}

def build_agent_context(instance: str, *, role: str | None,
                         workspace_boilerplate: str, instance_notes: str | None,
                         review_files: list[str], setup_md: str | None,
                         review_include: str | int = "latest") -> AgentContext:
    # Returns {context: str, sources: {role_template, workspace, instance}}
    # instance_notes = content of context.md (stable PR anchor; NOT notes.md)
    # review_include: "latest" (default) | "all" | int (past N)
    # Non-default review_include raises NotImplementedError until implemented.
    # Default bundle: setup_md + instance_notes (context.md) + latest review snapshot.

def status_has_setup_md(instance: str, instance_dir: str,
                          setup_md_present: bool) -> StatusResult: ...
```

Spec gaps:
- Collision disambiguation strategy (suffix) — resolved as `-2`, `-3`
- `setup.md` include format in `build_agent_context` — concatenated into context string
- `review_include` non-default paths deferred (raise NotImplementedError)

---

### owm.ports

```python
# Types
@dataclass
class PortPair:
    http_port: int
    gevent_port: int  # always http_port + 1

@dataclass
class PortConflict:
    # Instance conflict (from honour_pinned_port):
    instance: str | None
    running: bool | None
    requires_confirmation: bool | None
    # Process conflict (from check_port_at_start):
    pid: int | None
    name: str | None
    cmdline: str | None
    options: list[str] | None  # ["kill", "reassign"]

class PortExhaustedError(OwmError): ...

# Functions
def assign_port(pool: dict) -> PortPair:
    # pool = {"range": [low, high], "owm_range": [...], "occupied": set[int]}
    # Finds first free consecutive pair [N, N+1]; skips pair if either occupied.
    # Raises PortExhaustedError (PORT_EXHAUSTED) if range full.

def honour_pinned_port(pinned_http: int, occupied: set[int], *,
                        existing_instances: list[dict] | None = None) -> HonourResult:
    # Returns {http_port, gevent_port, conflict?}
    # Stopped holder → conflict.requires_confirmation = True
    # Running holder → raises OwmError(PORT_CONTESTED)

def check_port_at_start(http_port: int, *,
                          bound_by: dict | None = None,
                          next_free_port: int | None = None,
                          resolution: str | None = None) -> StartPortResult:
    # Returns {conflict?, new_http_port?, config_updated?, http_port?}

def evict_port(instance: str, old_port: int, new_port: int, reason: str) -> EvictResult:
    # Returns {logged: bool, old_port, new_port}

def find_conflicting_process(port: int) -> dict | None: ...
def get_eviction_log(log_path: str) -> list[dict]: ...
def eviction_count_in_window(evictions: int, threshold: int, window_days: int) -> EvictionCheck:
    # Returns {alert: bool, recommendation?: str}
```

Spec gaps:
- Rolling window: calendar week or 7×24h? Default: 7×24h from now.
- Non-interactive conflict resolution (agent context) — behavior not specced.

---

### owm.addons

```python
def resolve_addons_path(workspace_repos: dict, instance_repos: dict,
                         workspace_root: str, instance_name: str,
                         instances_dir: str) -> list[str]:
    # Declaration order = priority order. Optional repo_priority overrides TOML key order.
    # shared=True → _shared/<repo>/<branch>/<addons_path>
    # shared=False → instances/<name>/<repo>/<addons_path>
    # has_addons=False → excluded; repo absent from instance → silently excluded
    # addons_paths missing → default ["."] → resolves to repo root
```

Spec gaps:
- TOML key order preservation — Python 3.12 dicts preserve insertion order; confirm parser does too.

---

### owm.env

```python
def resolve_env(instance: str, workspace_root: str, *,
                instance_http_port: int | None = None,
                instance_gevent_port: int | None = None) -> dict[str, str]:
    # Returns: ODOO_BIN, VENV_PYTHON, PSQL, DB_NAME, DB_PORT,
    #          INSTANCE_DIR, LOG_FILE, HTTP_PORT, GEVENT_PORT,
    #          ODOO_CONF, WORKSPACE_DIR, SCRIPTS_DIR, WORKSPACE_SCRIPTS_DIR

def format_env(env: dict, fmt: str | None) -> str:
    # fmt: "dotenv" | "json" | "shell" | None (human-readable default)
```

Spec gaps:
- `SCRIPTS_DIR` when instance has no scripts.scripts_dir — return empty string or absent?
- `WORKSPACE_SCRIPTS_DIR` when workspace has no scripts section.

---

### owm.worktrees

```python
@dataclass
class WorktreeConfig:
    path: str
    per_instance: bool
    shared: bool

def resolve_worktree_path(repo: str, branch: str, shared: bool,
                           workspace_root: str, instance_name: str) -> WorktreeConfig: ...

def create_worktree(repo: str, branch: str, shared: bool,
                     workspace_root: str, instance_name: str) -> WorktreeResult:
    # Returns {action: "linked"|"created", path: str}

def push_branch(instance: str, repo: str, branch: str, *,
                readonly: bool, shared: bool, override: bool,
                override_allowed_in_config: bool = True) -> PushResult:
    # Raises OwmError(NOT_OWNED) if readonly and not override, or override not in config
    # Raises OwmError(SHARED_REPO) with raw git command in message if shared

def check_shared_commit_warning(repo: str, branch: str, shared: bool,
                                  has_new_commit: bool) -> WarningResult:
    # Returns {warning: bool, message: str}

def check_edit_allowed(readonly: bool) -> EditResult:
    # readonly blocks push only, not local edits/commits
```

Spec gaps:
- Override flag config key name in instance.toml (pre-impl: propose `[repos.<name>] override = true`).
- Shared worktree creation at init vs create boundary.

---

### owm.database

```python
def create_db(name: str, odoo_version: str, template: str | None,
               pg_port: int) -> CreateDbResult:
    # Returns {source: "template"|"blank", template?, full_install_required, warning?,
    #          connection: {host, password}, owner, operator_user, per_instance_role}

def reset_db(name: str, template: str, pg_port: int,
              seed_script: str | None) -> ResetDbResult:
    # Returns {restored_from, seed_script_run?, seed_script?, warning?}

def sync_db_from_template(template: str, *, instance: str | None = None,
                            instances: list[str] | None = None,
                            auto_sync: bool = False, opt_in: bool = False,
                            simulate_failure: bool = False) -> SyncDbResult:
    # Returns {synced?, synced_instances?, affected_instances?, backup_created?,
    #          backup_path?, backup_restored?, error?}

def check_template_staleness(template_age_days: int, threshold_days: int,
                               instance: str) -> StalenessResult:
    # Returns {stale: bool, warning: str | None}

def check_pg_reachability(pg_host: str, pg_port: int) -> ReachabilityResult:
    # Returns {method: "pg_isready", host, port}
```

Spec gaps:
- `DB_UNAVAILABLE` trigger on create — raises OwmError(DB_UNAVAILABLE) when pg_isready fails.
- Version string → cluster key mapping (default: exact string match on clusters dict).

---

### owm.venv

```python
def create_venv(instance: str, python_version: str, requirements_files: list[str],
                 patches: list[str], venv_dir: str) -> CreateVenvResult:
    # Uses uv; no pip fallback. Returns {python_version, created, tool: "uv",
    #                                     patches_applied, stamp, stamp_written}

def sync_venv_if_needed(venv_dir: str, current_stamp: str, recorded_stamp: str,
                          requirements_files: list[str], patches: list[str]) -> SyncResult:
    # Returns {synced, reason?, stamp_updated?, patches_applied?}

def rebuild_venv(instance: str, python_version: str, requirements_files: list[str],
                  patches: list[str], venv_dir: str) -> RebuildResult:
    # Delete + create. Returns {deleted, created, tool, patches_applied, stamp_written}

def compute_stamp(requirements_files: list[str], patches: list[str]) -> str:
    # Hash of file contents; deterministic

def stamp_changed(current: str, recorded: str) -> bool: ...

def resolve_patches(odoo_version: str, patches: dict[str, list[str]]) -> list[str]:
    # Literal key match; returns [] if no match
```

Spec gaps:
- Python version inference table (`"19.0"` → `"3.12"`) — not specced; needs lookup table before implementing.

---

### owm.sync

```python
def fetch_workspace(repos: list[str], repos_with_updates: list[str], *,
                     shared_worktrees: dict | None = None,
                     unreachable_repos: list[str] | None = None,
                     instances_on_shared: list[str] | None = None) -> FetchResult:
    # Returns {fetched, skipped, warnings, events_emitted,
    #          shared_worktrees_fast_forwarded, shared_worktree_hashes_logged,
    #          blocked_worktrees, db_snapshots_taken}

def sync_instance(instance: str, repo_states: dict, *,
                   rebase: bool = False, repo: str | None = None) -> dict[str, RepoStatus]:
    # Per-repo status: fast-forwarded|diverged|rebased|skipped

def push_instance(instance: str, *, repo: str | None = None,
                   all_repos: bool = False, repo_states: dict | None = None,
                   branch: str | None = None, branch_status: str | None = None,
                   owned: bool = True, shared: bool = False) -> dict | dict[str, dict]:
    # Raises OwmError(DIVERGED|NOT_OWNED|SHARED_REPO)

def reset_instance(instance: str, repo: str | None = None, *,
                    dirty: bool = False, force: bool = False,
                    has_local_commits: bool = False,
                    all_repos: bool = False, repo_states: dict | None = None) -> dict:
    # Raises OwmError(DIRTY_WORKTREE) if dirty and not force

def record_checkpoint(instance: str, repo_hashes: dict[str, str],
                       db_snapshot_path: str, manual: bool,
                       note: str | None = None) -> Checkpoint: ...

def rollback_to_checkpoint(instance: str, checkpoint: dict, *,
                             current_hashes: dict | None = None) -> RollbackResult: ...
```

Spec gaps:
- Smart-skip implementation for fetch (ls-remote vs timestamp).
- Auto-checkpoint trigger conditions (all three checks must pass simultaneously?).
- Rollback CLI/MCP surface — deferred per spec.

---

### owm.workspace

```python
def init_workspace(workspace_root: str, workspace_toml_content: str, *,
                    docker_context: bool = False,
                    existing_repos: list[str] | None = None,
                    pg_port: int = 5432,
                    operator_user: str | None = None,
                    superuser_exists: bool = False) -> InitResult:
    # Returns {bare_clones_created, skipped, db_clusters_provisioned,
    #          proxy_block_written, proxy_block_target, local_ca_installed,
    #          postgres: {superuser_created, superuser_role, skipped}}
    # docker_context=True: skips CA cert + system proxy
```

Spec gaps:
- Proxy implementation TBD (nginx vs caddy) — `proxy_block_target = "owm_dashboard"` is the target.

---

### owm.instance

```python
def generate_instance_conf(instance_name: str, http_port: int, gevent_port: int,
                             workers: int, db_name: str | None = None,
                             db_port: int | None = None) -> str | dict:
    # Pure transform → Odoo ini-format config string (or dict for testing)
    # Includes: longpolling_port, workers, dbfilter=^<name>$

def new_instance(name: str, repos: dict, workspace_root: str, *,
                  already_exists: bool = False) -> NewResult:
    # Writes instance.toml only; no materialisation.
    # Returns {toml_path, toml_content, materialised: False}
    # Raises OwmError(ALREADY_EXISTS) if exists

def create_instance(name: str, workspace_root: str, *,
                     instance_exists: bool = False,
                     toml_changed: bool = True,
                     repo_changes: list[dict] | None = None,
                     new_repos: list[str] | None = None,
                     removed_repos: list[str] | None = None) -> CreateResult:
    # Idempotent. Returns {status, created, updated, skipped, conflicts?,
    #                       worktrees_created, db_created, port_reserved,
    #                       nginx_block_written, odoo_conf_generated}

def start_instance(instance: str, *, wait: bool = False,
                    simulate_healthy: bool | None = None,
                    timeout_seconds: int | None = None,
                    already_running: bool = False) -> StartResult:
    # Returns {status, pid, events_emitted, message?, url?}
    # Raises OwmError(START_TIMEOUT) if wait=True and times out

def stop_instance(instance: str, *, wait: bool = False,
                   simulate_clean_exit: bool | None = None,
                   timeout_seconds: int | None = None,
                   running: bool = True) -> StopResult:
    # Never auto-kills. Returns {status, pid?, events_emitted?, hint?}

def kill_instance(instance: str, *, running: bool, pid: int | None = None) -> KillResult: ...

def restart_instance(instance: str, *, wait: bool = False,
                      simulate_stop_clean: bool | None = None,
                      timeout_seconds: int | None = None,
                      new_pid: int | None = None) -> RestartResult:
    # Raises OwmError(STOP_TIMEOUT) without implicit kill

def health_check(instance: str, *, pid: int | None = None,
                  http_alive: bool = False, process_running: bool = True,
                  timed_out: bool = False, unmanaged: bool = False,
                  port: int | None = None) -> HealthResult:
    # Returns exact dict: {status, pid?, http_alive?, url?, port?}
    # Scope: process + HTTP only; DB/venv/modules are owm_validate
```

Spec gaps:
- Venv sync timing relative to spawn (before or after?).
- Module install blocking vs async at start.
- Health URL scheme during "starting" phase.

---

### owm.modules

```python
def install_modules(instance: str, configured_modules: list[str],
                     installed_modules: list[str]) -> InstallResult:
    # Returns {installed, skipped, odoo_bin_called, odoo_bin_args?}
    # If all present: skipped=True, installed=[]

def upgrade_modules(instance: str, modules: list[str] | None, *,
                     reinstall: bool = False) -> UpgradeResult:
    # None → -u all. Returns {stopped_before, modules, restarted, odoo_bin_called, reinstall?}

def check_modules_present(instance: str,
                            configured_modules: list[str]) -> list[str]:
    # Returns list of missing modules
```

---

### owm.scripts

```python
def parse_ndjson_output(raw: str) -> list[dict]:
    # Valid statuses: OK, FAIL, WARN, NONE

def run_script(instance: str, script_name: str, *,
                failure_mode: str = "row_level",
                ndjson_output: str | None = None,
                contract: dict | None = None) -> ScriptResult:
    # Returns {status, summary: ScriptSummary, rows, rows_run?, abort_reason?,
    #          blocker?, contract_violation?}

def compare_instances(instance: str, *, base: str | None = None,
                       workspace_compare_pairs: list | None = None,
                       base_rows: list | None = None,
                       feat_rows: list | None = None,
                       expected_changes: list | None = None,
                       base_instance_exists: bool = True) -> CompareResult:
    # Returns {status, base_instance, feat_instance, summary, unexpected?, error?,
    #          missing_instance?}

def scaffold_script(instance: str, script_name: str) -> ScaffoldResult:
    # Returns {path, content} — contract-level template
```

Spec gaps:
- Abort via exit code vs special row — which takes precedence?
- Contract declaration format in script file.

---

### owm.archive

```python
def archive_instance(instance: str, workspace_root: str, *,
                      running: bool = False,
                      discard_db: bool = False,
                      discard_artifacts: bool = False) -> ArchiveResult:
    # Raises OwmError(INSTANCE_RUNNING) if running.
    # Returns {preserved, archive_path, db_dumped, db_dump_path,
    #          worktrees_removed, live_db_dropped, port_freed}

def create_from_archive(name: str, workspace_root: str, mode: str, *,
                          archive_date: str | None = None,
                          original_port: int | None = None) -> RestoreResult:
    # mode="restore": worktrees_created, db_restored, port_freshly_assigned
    # mode="fresh": old_archive_renamed_to, old_archive_preserved, then fresh create

def delete_archive(name: str, workspace_root: str, confirmed: bool) -> DeleteResult:
    # Raises if not confirmed. Returns {status, path}

def detect_archive_conflict(name: str, workspace_root: str, *,
                              archive_exists: bool, archive_date: str,
                              mode: str, flag: str | None = None) -> ConflictResult:
    # mode="human": returns {conflict, archive_date, options}
    # mode="agent": raises if flag not "restore" or "fresh"
```

---

### owm.adoption

```python
def detect_unmanaged_processes(configured_instances: dict,
                                 running_processes: list[dict]) -> list[dict]: ...

def adopt_process(instance: str, pid: int, configured_port: int, process_port: int, *,
                   force: bool = False) -> AdoptResult:
    # Writes pid to state.json. Returns {status, pid, pid_written_to_state, manageable}
    # Port mismatch + force=False → {status: "needs_confirmation", warning}

def status_with_unmanaged(configured_instances: dict,
                            running_processes: list[dict]) -> UnmanagedStatus:
    # Returns {unmanaged, instance_conflicts}
```

Spec gaps:
- Detection method (ps, /proc, port binding scan) — implementation-defined.
- `owm_adopt` MCP tool deferred per spec.

---

### owm.cli

```python
def infer_instance_from_cwd(cwd: str, workspace_root: str, instances_dir: str, *,
                               explicit_name: str | None = None) -> CwdResult:
    # Returns {instance: str | None}

def delete_instance(instance: str, *, running: bool, force: bool,
                     has_session_notes: bool = False,
                     open_compare_pairs: list | None = None,
                     workspace_compare_pairs: list | None = None) -> DeleteResult:
    # running=True → raises. force=False → checklist. force=True → deletes all.

def rename_instance(instance: str, new_name: str, *, running: bool,
                     workspace_compare_pairs: list | None = None) -> RenameResult: ...

def show_logs(instance: str, n: int, follow: bool, level: str | None, *,
               simulated_lines: list | None = None) -> LogsResult: ...

def db_dump(instance: str, out: str | None, workspace_root: str) -> DumpResult: ...

def db_restore(instance: str, path: str, workspace_root: str, *,
                running: bool = False) -> RestoreResult:
    # Relative path → resolved under _dumps/<instance>/
    # running=True → raises

def validate_instance(instance: str, *, live: bool = False,
                       toml_valid: bool = True, **state_kwargs) -> ValidateResult: ...

def adopt_instance(instance: str, pid: int, **kwargs) -> AdoptResult: ...
```

Spec gaps:
- `--follow` interface (generator, async stream, subprocess handle).
- Delete checklist configuration location.
- CWD walk-up stopping condition when no workspace.toml found.

---

### owm.mcp

Thin surface: each `owm_*` function calls the appropriate underlying module function,
converts exceptions to `ErrorResponse` dicts, and returns JSON-serialisable results.
No business logic lives here — it is exclusively response-shaping.

```python
# 25 tools — all accept keyword args matching test call sites
owm_status(instance=None, include_repos=True, include_ports=True, include_unmanaged=True)
owm_ps(simulated_managed=None)
owm_validate(instance, live=False)
owm_env(instance)
owm_audit_log(n=50, level=None, since=None)
owm_new(instance, repos, already_exists=False)
owm_create(instance, toml=None, repos=None, **simulate_kwargs)
owm_start(instance, wait=False, **simulate_kwargs)
owm_stop(instance, wait=False, running=True, **simulate_kwargs)
owm_kill(instance, running=True, pid=None)
owm_restart(instance, wait=False, **simulate_kwargs)
owm_health(instance, **simulate_kwargs)
owm_archive(instance, running=False, discard_db=False)
owm_delete(instance, force=True, running=False)
owm_rename(instance, new_name, running=False)
owm_fetch()
owm_sync(instance, repo=None, rebase=False, simulate_repo_states=None)
owm_push(instance, repo, simulate_diverged=False)
owm_reset(instance, repo, force=False, simulate_dirty=False)
owm_run_script(instance, script, **simulate_kwargs)
owm_get_script_failures(ndjson_path)
owm_compare(instance, base=None, **simulate_kwargs)
owm_upgrade(instance, modules, in_place=False, workers=2, simulate_failure=False)
owm_db_reset(instance)
owm_db_dump(instance, out=None)
owm_db_restore(instance, path, running=False)
owm_logs(instance, n=50, level=None)
owm_agent_context(instance, role=None, has_instance_notes=True)
```

Pre-implementation decisions:
- `simulate_*` parameters pass through to underlying module functions as injection parameters.
- `owm_ps` reads `state.json` per instance dir; no git calls, no toml parsing.
- `owm_adopt` MCP tool explicitly deferred (CLI only).

---

## Deferred test concerns

- `test_mcp_surface.py:test_owm_ps_reads_only_state_json` — performance contract (no git calls)
  cannot be asserted as a unit test; requires integration test with subprocess mocking.
  Test now asserts shape only. ✓ (fixed this session)

- `test_mcp_surface.py:test_owm_compare_parallel_vs_sequential` — `--parallel`/`--sequential`
  flags specced at CLI level; MCP equivalent not shown in spec. Deferred until CLI impl.

- `test_fetch_sync.py` rollback tests — CLI/MCP surface deferred per spec Deferred section.

---

## Pre-implementation decisions (open)

1. **`build_agent_context` review/ grouping** — current spec says "latest review file only";
   agreed to include all files grouped by type. Grouping strategy (by trigger prefix? by date?)
   not yet resolved. Decide before implementing `owm.session_context`.

2. **On-disk state** — ratified: `state.json` single file per instance. ✓

3. **Python version inference table** — `"19.0"` → `"3.12"` etc. Needed before `owm.venv`.
   Run a case-interviewer pass or decide inline.

4. **Override flag in instance.toml** — exact key name for "push override allowed" not specced.
   Propose `[repos.<name>]\noverride = true`. Confirm before `owm.worktrees`.

5. **`simulate_*` injection parameters** — kept as real production parameters. ✓

6. **Port assignment** — consecutive pairs `[N, N+1]`, single range. ✓

---

## Tracer bullet assessment

No tracer bullet recommended. Every inter-module contract is explicit and tested:
`owm.config` produces `WorkspaceConfig`/`InstanceConfig`; every consumer specifies
exactly what fields it reads. `owm.instance` produces `HealthResult`; `owm.mcp` asserts
its exact shape. The seams are specified. Implement bottom-up in DAG order.

Note for implementation-writer: resist the pull toward horizontal layering (complete all
of `owm.config` then all of `owm.ports` etc. without running tests in between). Run the
test suite after each module. `owm.errors` and `owm.config` unlock the most downstream
tests — get these green first.
