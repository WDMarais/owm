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

**Risk:** spec.md states push safety invariants (refuse unowned/shared branches) are
"non-negotiable, must survive any future refactor." Currently these checks live in
`mcp.py` (lines 205–215), not in `sync.py` or `worktrees.py`. A CLI caller that
calls `push_instance` directly bypasses them entirely.

```python
# mcp.py — business logic that belongs in sync.py/worktrees.py
if repo == "odoo":
    return format_error("odoo is a shared repo", "SHARED_REPO", ...)
if instance.startswith("review-"):
    return format_error(..., "NOT_OWNED")
```

The spec's "must survive any future refactor" constraint cannot be satisfied if the
invariant only exists in the MCP dispatch layer. It needs to be enforced in
`push_instance` / `push_branch` directly.

---

## 3. `meta` key collision in `parse_workspace_config`

**Risk:** `parse_workspace_config` extracts `[repos.meta]` by calling
`repos_raw.pop("meta", {})` (config.py line 151). TOML deserializes `[repos.meta]`
as `repos["meta"]`, so this works — but a workspace that has a repo literally named
`"meta"` (declared as `meta = "git@..."` under `[repos]`) would have that repo
silently discarded from `repos_raw` and misinterpreted as metadata. The key `meta`
is effectively reserved with no spec documentation of that constraint.

**What needs addressing:** either document that `meta` is a reserved repo name (and
validate against it explicitly), or move `[repos.meta]` to a separate top-level key
(`[repo_metadata]` or `[repos_meta]`) that cannot collide with a real repo name.

---

## 4. `generate_instance_conf` returns a dict, not an ini string

**Risk:** `generate_instance_conf` in `config.py` currently returns a `dict`. Odoo
expects an ini-format config file. ARCHITECTURE.md says "Pure transform → Odoo
ini-format config string (or dict for testing)" — so the dict-returning stub is
intentional for now. But the function signature gives no indication of this, and
`instance.py` calls it without any conversion step. When the real implementation
wires this path, the output needs to be an ini string written to `instance.conf`. If
the conversion step is missed, Odoo gets a Python dict as its config file.

**What needs addressing:** add a comment to `generate_instance_conf` noting that it
must return ini-format string in the real implementation, or split into
`_generate_instance_conf_dict` (test oracle) and `generate_instance_conf` (real,
returns string) to make the gap explicit.

---

## 5. `dbfilter` set before subdomain model ships

**Risk:** re-owm's `generate_instance_conf` sets `dbfilter = ^<instance_name>$`
unconditionally. owm's DESIGN.md has an explicit note *against* this for local dev:

> `dbfilter` should not be set in generated `instance.conf` for local dev instances.
> Browsers key session cookies to domain only (not port), so `localhost:8101` and
> `localhost:8102` share a cookie jar — a restrictive `dbfilter` causes Odoo to
> reject sessions from other instances and log the user out silently.

re-owm's spec.md justifies setting dbfilter by the subdomain model (`feat-789.localhost`
gives each instance a distinct hostname, so the cookie-jar collision no longer
applies). That reasoning is sound — *once the subdomain model is in place*. But the
subdomain model depends on nginx proxy blocks, a local CA cert, and `*.localhost`
HTTPS, all of which are described as TBD in spec.md and unimplemented in the current
codebase.

**What needs addressing:** if re-owm is used before the subdomain model ships (e.g.
in a transition period, or because nginx setup is deferred), setting dbfilter will
reproduce the exact silent-logout bug owm was designed to avoid. Either gate
`dbfilter` generation on whether the proxy model is active, or document prominently
that the dbfilter change is only safe after subdomain routing is in place.

---

## 6. `ARCHIVE_CONFLICT` and `CONFIRMATION_REQUIRED` are undocumented error codes

**Risk:** `errors.py` defines `ARCHIVE_CONFLICT` and `CONFIRMATION_REQUIRED` (lines
22–23) but neither appears in spec.md's error taxonomy table. An MCP consumer
receiving these codes has no documented semantics for how to handle them.

**What needs addressing:** add both codes to the spec.md error taxonomy table with
their meaning, trigger conditions, and expected consumer behavior.

---

## 7. `generate_instance_conf` is in `config.py`, not `instance.py`

**Issue:** `generate_instance_conf` is a generator (takes runtime params, produces
Odoo config), not a parser. Parsers belong in `config.py`; generators belong in the
module that owns the thing being generated. ARCHITECTURE.md's per-module interface
assigns it to `owm.instance`. It currently lives in `owm.config` and is imported
from there by `instance.py`.

The misplacement matters because `config.py` is the highest-fanout module (imported
by 17/20 modules). Adding non-parsing responsibilities here makes it harder to
reason about what `config.py` is for and creates an awkward import direction
(`instance.py` should produce things, not consume generators from `config.py`).

**What needs addressing:** move `generate_instance_conf` to `instance.py` where
ARCHITECTURE.md placed it.

---

## 8. `mcp.py` depends on `cli.py` — dependency direction is inverted

**Issue:** `mcp.py` imports `delete_instance`, `rename_instance`, `show_logs`,
`db_dump`, `db_restore` from `cli.py`. The intent is that these functions are shared
between the CLI and MCP surfaces. That's fine functionally, but the placement in a
module named `cli.py` implies CLI-wiring code — a future reader will not expect MCP
to depend on CLI.

The incumbent ran into the same problem in the other direction (MCP was subprocess-
wrapping the CLI), and its DESIGN.md explicitly flags the refactor toward direct
library calls as the right direction. re-owm partially reproduces the coupling by
putting shared operations in a CLI-named module.

**What needs addressing:** rename `cli.py` to something that reflects its actual
scope (`operations.py`, `commands.py`), or split it — CWD inference and CLI dispatch
stay in `cli.py`, shared operation functions move to a module that both CLI and MCP
can import without the naming confusion.

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
