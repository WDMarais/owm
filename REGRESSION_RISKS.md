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

**Resolution (d0ec185):** Function moved to `instance.py` and carries a `# TODO`
comment explicitly noting the real implementation must emit an ini-format string
written to `instance.conf`. Deferred to I/O sweep.

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

**Resolution (23d7300):** `cli.py` renamed to `operations.py`. All import sites
updated. CLI-specific dispatch will live in `cli.py` once wired during the I/O sweep;
shared operation functions stay in `operations.py`.

---

## 9. `find_conflicting_process` and `get_eviction_log` are I/O stubs — deferred to I/O sweep

**Resolution:** These are pure I/O shims, not business-logic paths. Injection
parameters would be removed when the real implementation lands, so adding them
now is the wrong pattern. Their callers (`check_port_at_start` via `bound_by=`,
`eviction_count_in_window` via `evictions=`) are already fully exercised by the
test harness through their own injection parameters.

Both functions now carry comments naming the real I/O call (`psutil` /
`ss -tlnp` for process lookup; file read for the eviction log). Full
implementation is deferred to the I/O sweep.
