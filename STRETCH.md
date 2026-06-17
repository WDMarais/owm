# STRETCH — template-DB + worktree-check pass (handoff)

Carry file so this pass can resume on either laptop. Branch:
`template-db-and-worktree-check`. Delete this file when the pass lands.

## Why this pass exists

Distilled from a planning session over owm / re-owm / agent-skills and the
real-usage notes (`~/notes/sessions`, `~/dev-instances`). Those refs were
*input* to the plan below — they are not needed again to do the work. The
strategic frame: re-owm's job is to collapse the activation energy of local
testing (seconds-not-minutes instances), make state failures loud, and enable
measurement. The items here are the concrete expression of the first lever.

## Work items

### 1. Worktree `.git` existence check  (warmup, one-liner + test)
`create_worktree` (src/owm/worktrees.py:84) decides "worktree already exists"
with bare `os.path.exists(cfg.path)` (lines 100 and 111). A stray plain
directory at the worktree path therefore silently counts as "exists" and
creation is skipped. Tighten the existence test to require a `.git` entry
(file or dir) inside the path, not just that the path exists. Add a test:
plain dir at the path -> worktree still created.

### 2a. Wire template into the create flow  (behaviour change, own commit)
`_materialise_instance` (src/owm/instance.py, ~line 584) creates the DB via the
naive `_create_instance_db` (~lines 277-288), which never reads
`conf.database.template` — every create is blank + full Odoo boot install.
Change it to `create_db(template=conf.database.template, ...)`
(src/owm/database.py — `create_db` already exists and is tested, just unused).
- template set  -> clone from template, skip module install
- template None -> current blank + install path, unchanged
This is a behaviour change (create stops always-installing); keep it a separate
commit from 2b. New tests in test_instance_lifecycle_create.py: template-based
create, and "no module install performed when cloned".

### 2b. `owm template create` with stop-guard  (new primitive)
Nothing currently *mints* a template — `db-reset`/`sync_db_from_template`
consume one but nothing produces one. Add:
- `create_template_from_instance()` in database.py using
  `createdb --template=<instance-db>`.
- **Stop-guard (locked decision):** refuse if the instance is running or the DB
  has active connections; error points at `owm stop`. (`createdb --template`
  requires the source DB idle — matches the connection constraint owm already
  documents.)
- CLI: `owm template create <instance> <name>` + `owm template list`.
- MCP: mirror both.
- Tests: stop-guard refusal (running / active connections) + happy-path clone.

### 2c. Deferred — NOT this pass
Workspace-level `template_mapping` (version -> default template) auto-populating
`[database].template` in new-toml; CLI-expose `sync_db_from_template`; template
GC/rotation. Explicitly out of scope.

## Locked decisions (do not re-litigate)
- Snapshot mechanism = `createdb --template` + stop-guard (not `pg_dump`).
- 2a and 2b are separate commits; 2a is a behaviour change, flag it as such.
- **owm-status-cache skill: dropped.** It was incidental complexity working
  around owm's un-splittable `status`. re-owm's cost-split obviates it AT THE
  SOURCE — but the obviating tier (`owm audit` -> `audit.json`, specced in
  ARCHITECTURE.md ~L94-113) is **specced, not built**. Today `owm status` is a
  hybrid that runs git per repo per instance inline (api.py:184 workspace_status
  -> _repo_alerts api.py:65), reproducing owm's 15-20k-tokens/session problem.
  So the real follow-up is **implement `owm audit` + `audit.json` + `--cached`
  + MCP tool**, NOT a cache hook. Keep the BRIEF's digest shape (only notable
  instances: running/orphaned/unhealthy, omit stopped). This is its own pass,
  after template-DB lands — not tonight.

## Portability / where to run what
- Code + mocked unit/CLI tests: portable anywhere with uv + Python 3.12.
  `uv run pytest -q`. Do items 1, 2a, 2b and their unit tests on any machine.
- **Integration / smoke tests need the workspace machine**: real Postgres +
  populated `OWM_WORKSPACE` (~/dev-instances). The DB-clone and stop-guard
  behaviour must be verified there. Mark those `-m integration` runs as
  "verify on workspace machine" if working elsewhere.

## Per-CLAUDE.md
GitNexus: run `gitnexus_impact` before editing `create_worktree`,
`_materialise_instance`, `create_db`; `gitnexus_detect_changes` before commit.
