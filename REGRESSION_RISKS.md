# re-owm Regression Risks

Concerns where re-owm appears to go in the wrong direction or leaves a spec gap
that could introduce a regression relative to owm. Items are behavioral or
structural issues — not "not yet implemented" gaps.

---

## 1. Readonly/shared worktree checkout — `wt/` branch gap

**Resolution:** re-owm deliberately does not use owm-style shadow branches.
`wt/` existed in owm because `_shared/` did not — instances each got their own
checkout of dev, hence per-instance shadow branches. re-owm's `_shared/<repo>/<branch>/`
convention makes them unnecessary: one canonical checkout per branch, all instances
read from the same path.

For the `readonly+same-branch` case (two instances declaring the same branch as
readonly), re-owm uses `_shared/<repo>/<branch>/` rather than per-instance worktrees.
If two instances want independent edits to the same base, that's the
`feat-789-dev:dev` pattern — an instance-owned branch rebased on the shared base,
not simultaneous checkouts of the same branch.

The update-propagation risk (fast-forwarding `_shared/` affects all instances at
once) is addressed by the checkpoint mechanism: save confirmed-working repo hashes
+ DB state before updating, roll back if the fast-forward breaks something.

See ARCHITECTURE.md → owm.worktrees for the full convention.

---

## 2. Push safety invariants enforced only at the MCP layer

**Resolution (949132a):** `owm_push` now derives `shared`/`owned`/`branch_status`
from context and delegates to `push_instance` in `sync.py`, which raises
`OwmError(SHARED_REPO/NOT_OWNED/DIVERGED)`. The MCP layer only shapes the response.
Direct callers of `push_instance` get the same invariants enforced.

---

## 3. `meta` key collision in `parse_workspace_config`

**Resolution (f9069a6):** `parse_workspace_config` now raises `ValueError` with a
clear message if `meta` appears as a plain repo URL. `meta` is documented as a
reserved key; the error directs users to rename the repo.

---

## 4. `generate_instance_conf` returns a dict, not an ini string

**Resolution (d0ec185 + I/O sweep):** Moved to `instance.py` and now emits an
ini-format string (`[options]` + joined lines, `-> str`). The create path
(`instance.py:453`) and `regen-conf` (`cli.py:1062`) render it and write it to
`instance.conf`. No longer a dict; no longer deferred.

---

## 5. `dbfilter` set before subdomain model ships

**Resolution (43dc7bd):** `generate_instance_conf` now accepts `proxy_active: bool = True`.
`dbfilter` is only emitted when `proxy_active=True`. Callers before the subdomain
proxy ships pass `proxy_active=False` to avoid the session-cookie collision bug.

---

## 6. `ARCHIVE_CONFLICT` and `CONFIRMATION_REQUIRED` are undocumented error codes

**Resolution (f81e085):** Both codes added to the error taxonomy table in
ARCHITECTURE.md (owm.errors section) with trigger conditions and consumer actions.
The full taxonomy table was migrated from spec.md to ARCHITECTURE.md at the same time.

---

## 7. `generate_instance_conf` is in `config.py`, not `instance.py`

**Resolution (d0ec185):** Moved to `instance.py`. Import sites in both test files
updated accordingly. `config.py` is now parsers-only.

---

## 8. `mcp.py` depends on `cli.py` — dependency direction is inverted

**Resolution (23d7300 + I/O sweep):** `cli.py` renamed to `operations.py`;
shared operation functions live there and `mcp.py` imports from the domain
modules / `operations`, not `cli` (verified: no `cli` import in `mcp.py`).
`cli.py` is now the full Click command dispatch (~30 commands) over those
operations — the "wired during the I/O sweep" step is done.

---

## 9. `find_conflicting_process` and `get_eviction_log` were I/O stubs

**Resolution (dd263f5):** Both now do real I/O — `find_conflicting_process`
uses `psutil.net_connections`; `get_eviction_log` reads the JSONL log file.
Production start/status paths call `find_conflicting_process` directly
(`instance.py:590`, `api.py:31`/`86`); no longer deferred (implemented after
the original stub note `3b30616`).

Residual (not a stub — a wiring gap): the port-conflict *resolution* layer
(`check_port_at_start`, `evict_port`, `eviction_count_in_window`) is implemented
and unit-tested via injection params (`bound_by=`, `evictions=`) but not wired
into any `owm start` UX — start only *detects* a conflict, it doesn't offer the
kill/reassign flow these decide. Wire it or mark the resolution UX as deferred.
