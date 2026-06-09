# INCOMING

Parking lot for things that need more thought before landing in ARCHITECTURE.md or spec.md.
Items here are unresolved design questions, not bugs or tasks.

---

## State caching and staleness model

Currently ARCHITECTURE.md says repo sync state is "derived from live git calls, not stored
on disk." That's probably wrong as a final answer.

The better model is likely event-driven writes: state is written when the event that changes
it occurs, read from disk until the next write. TTL is a fallback only for state we haven't
wired explicit invalidation to yet.

Rough tiers to think through:
- `state.json` — already event-driven (start/stop/kill). Fine.
- Git sync state — natural write point is `owm fetch`; a `sync_state.json` after fetch.
- Venv/DB health — invalidated by create/db-restore/explicit venv ops; essentially static
  between those events. TTL of hours fine as fallback, but event-driven is cleaner.
- Port health — derived from `state.json` + a live ss/psutil check; the only one that
  genuinely needs polling, and only to catch external squatters.

Guiding principle: if the dashboard surfaced something, it's because it read from a layer
that also serves CLI/MCP — not because the dashboard computed something exclusive. State
accumulates on disk; dashboard reads it.

Questions to resolve before formalizing:
- What exactly does each event write, and where?
- How does TTL interact with explicit refresh (`owm fetch --force`)?
- Is there a single `status_cache.json` per instance, or per-concern files?
- Does `owm status` on a given instance always re-derive, or read + optionally refresh?

---

## owm-workspace compat — probe findings (2026-06-01)

Ran re-owm read-only against the live owm workspace (`~/dev-instances`, 18 owm instances) to find
coexistence/adoption gaps. `status` was fully compatible — discovery, running/stopped state, and
port-conflict classification (`probable_orphan` on `cd-1753:8107`) all correct. Every divergence
is at the per-instance derivation layer. Classified better / different / worse:

**Contract divergences (different, arguably better — but break coexistence):**
- env var names: re-owm emits `DB_NAME`/`HTTP_PORT`/`VENV_PYTHON`; owm's documented `.env`
  contract uses `ODOO_DB`/`ODOO_PORT`/`VENV` (and owm's `VENV` is the dir, re-owm's `VENV_PYTHON`
  is the binary). re-owm's are cleaner, but anything sourcing owm's `.env` breaks. Q: should
  adoption/compat mode emit an owm-compatible alias set?
- `LOG_FILE` = `instance.log` vs owm `odoo.log` (re-owm separates structured oplog from the odoo
  log). Cleaner; breaks hardcoded `odoo.log` consumers.
- `validate` flags every owm `instance.conf` as out-of-sync (different conf generation). Q: should
  adoption re-emit confs, or tolerate owm's format?

**Capability gap (different, with loss):**
- `branches` was redefined: re-owm's lists bare-repo branch inventory (`_repos/*.git`,
  workspace-global); owm's `branches <instance>` listed the checked-out branch per per-instance
  worktree. The per-instance "what's checked out" view (used in PR review) is gone — add alongside
  the `diff` / `sweep` / `check-modules` parity gaps.

**Through-line:** re-owm can *observe* an owm workspace fine; it can't cleanly *operate on* or
*adopt* owm-created instances until (a) `env` reads config instead of re-deriving, and (b) there's
an adoption path for the env-var + conf-format + log-name contracts. The core (config, ports,
db-ops) is sound — the rough edges are the `env` stub and contract-aliasing.
