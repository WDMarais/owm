# re-owm implementation notes

Context for running implementation-writer on this project. Read alongside the skill.

---

## Implied module inventory

Extracted from stub comments across 19 test files:

| Module | Test file(s) | Notes |
|---|---|---|
| `owm.errors` | `test_error_taxonomy.py` | Pure constants, no deps |
| `owm.config` | `test_config_schemas.py` | Pydantic models for workspace.toml + instance.toml |
| `owm.ports` | `test_port_assignment.py` | Port pair assignment |
| `owm.addons` | `test_addons_resolution.py` | `resolve_addons_path` |
| `owm.env` | `test_owm_env.py` | `resolve_env`, `format_env` |
| `owm.worktrees` | `test_worktrees.py` | Path resolution, push permission |
| `owm.venv` | `test_venv_management.py` | uv-backed venv creation, stamp |
| `owm.database` | `test_database_lifecycle.py` | DB create/reset/template/dump/restore |
| `owm.audit` | `test_audit_log.py` | Structured append-only log |
| `owm.session_context` | `test_session_context.py` | setup.md, review/ naming |
| `owm.git_sync` | `test_fetch_sync.py` | fetch/sync/push/reset/rollback |
| `owm.instance` | `test_instance_lifecycle_*.py` | create/start/stop/kill/restart/health |
| `owm.script_runner` | `test_script_runner.py` | NDJSON, failure tiers, compare pairs |
| `owm.archive` | `test_archive.py` | archive/restore/--fresh |
| `owm.adoption` | `test_adoption.py` | Detect + adopt unmanaged processes |
| `owm.cli` | `test_cli_commands.py` | delete/rename/logs/db-dump/restore/validate |
| `owm.mcp` | `test_mcp_surface.py` | All MCP tools + safety invariants |

---

## Suggested DAG order

```
owm.errors          (leaf — pure constants)
owm.config          (leaf — parses TOML, no owm deps)
owm.ports           (depends on config for port range)
owm.addons          (depends on config)
owm.env             (depends on config)
owm.audit           (depends on config for log path)
owm.worktrees       (depends on config + git)
owm.venv            (depends on config + worktrees)
owm.database        (depends on config)
owm.session_context (depends on config)
owm.git_sync        (depends on config + worktrees)
owm.instance        (depends on config + ports + worktrees + venv + database + audit)
owm.script_runner   (depends on instance + config)
owm.archive         (depends on instance + database)
owm.adoption        (depends on instance + ports)
owm.cli             (terminal — depends on all of the above)
owm.mcp             (terminal — thin surface over cli/instance/script_runner)
```

`owm.config` is the high-fanout priority — almost everything else imports it. Make
it green before touching anything else.

---

## Pre-implementation decisions needed

### 1. `simulate_*` parameter pattern in MCP tests

`test_mcp_surface.py` uses `simulate_instance_state="running"` etc. as call arguments
to control test paths without a real instance. At wiring time, decide:

**Option A — replace with `tmp_path` fixtures**: consistent with the rest of the suite;
`standard_workspace` + `standard_instance_toml` fixtures in conftest give you real disk
state. Recommended: MCP tools read from disk (same as dashboard state), so `tmp_path`
fixtures are the natural fit.

**Option B — keep `simulate_*` as real parameters**: adds a test-only code path into the
MCP layer. Avoid unless the fixture approach becomes genuinely unwieldy.

Resolve this before touching `owm.mcp`.

### 2. On-disk state contract (spec gap)

The spec does not have a section on what files owm writes and what they contain. This
surfaced post-harness-writer when thinking through dashboard testing. The dashboard layer
should read pure on-disk state; `build_dashboard_state(instance_dir)` is just file reads.

Before implementing `owm.instance` (which writes state) or `owm.mcp` (which reads it),
add a spec section covering:
- What files exist under `instances/<name>/` and what they contain
- PID file format
- Runtime state (ports in use, running status)
- What `owm.log` vs `instance.log` each contain

Run a brief case-interviewer pass to resolve this, or decide it explicitly with the user.

### 3. Port assignment — paired generation vs. independent storage

`gevent_port` is stored independently in instance.toml; `n+1` is only the default
generation convention, not a structural constraint. An instance with manually overridden
non-adjacent ports is valid. The spec should make this explicit.

Assignment algorithm: scan for first free consecutive pair [n, n+1]; skip the whole
pair if either port is occupied. Manual override via instance.toml is the escape hatch
for conflict cases — no need for separate HTTP and gevent port pools.

### 4. `DashboardState` type

Not yet in spec. If the dashboard is being implemented as part of re-owm (not separately),
define the type before `owm.mcp` or any server-side rendering layer. If dashboard is
deferred, skip for now.

---

## conftest fixtures to activate

These are written and ready in `tests/conftest.py`. They require `owm.config` to exist
before they become useful in integration tests:

- `standard_workspace` — 4-repo workspace on disk; enables most integration tests
- `standard_instance_toml` — feat-789 instance dir; enables lifecycle tests
- `make_upstream_repo` / `make_bare_clone` / `make_worktree` — needed for git sync tests

Pure-function tests (addons, ports, env, errors) don't need these and can go green
before `owm.config` exists.

---

## Permanently-green tests

Two tests in `test_error_taxonomy.py` were green before any implementation and must
stay green throughout:

- `test_all_codes_are_uppercase_strings`
- `test_all_codes_are_distinct`

Check after every commit.

---

## Python / tooling

- Minimum version: 3.12 (owm's own runtime; separate from per-instance Odoo Pythons)
- Package manager: `uv` (`uv add`, `uv run`)
- Run tests: `uv run python -m pytest tests/ -v`
- Per-section: `uv run python -m pytest -m section_marker tests/test_section.py -v`
