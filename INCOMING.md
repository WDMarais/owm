# INCOMING

Parking lot for things that need more thought before landing in ARCHITECTURE.md or spec.md.
Items here are unresolved design questions, not bugs or tasks.

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
