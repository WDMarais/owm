# re-owm Regression Risks

Concerns where re-owm appears to go in the wrong direction or leaves a spec gap
that could introduce a regression relative to owm. Items are behavioral or
structural issues — not "not yet implemented" gaps.

---

## 1. Readonly/shared worktree checkout — `wt/` branch gap

**Risk:** git will refuse to add the same branch in two worktrees simultaneously.
The incumbent solves this with shadow branches (`wt/<instance>/<repo>/<base>`) so
each instance gets a distinct local branch tracking the same remote ref. re-owm
uses `shared=true` and `readonly=true` flags but neither spec.md nor ARCHITECTURE.md
describes how readonly per-instance worktrees are checked out when the branch is
already live in another instance.

Example: `feat-789` and `review-101` both declare `product-core = "dev:dev+readonly"`.
Both attempt `git worktree add instances/feat-789/product-core dev`. The second call
fails because `dev` is already checked out. No recovery path is documented.

**What needs addressing:** either document that `readonly` implies a `wt/`-style
shadow branch (e.g. `wt/<instance>/<repo>/<base>`) and specify the branch naming and
lifecycle, or explain the mechanism that avoids the git conflict.

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

## 4. Spec and implementation contradict each other on within-repo addons ordering

**Risk:** spec.md shows:

```
instance with [multi-repo(feat, addons_paths=["primary_addons","secondary_addons"])]
→ addons_path = multi-repo/secondary_addons, multi-repo/primary_addons
# both folders contribute; reversed within the repo
```

ARCHITECTURE.md (resolved conventions table) says the opposite: "Within a repo's
`addons_paths` list, declaration order is preserved (first-declared = highest
priority; users write explicit priority order, same as PATH/PYTHONPATH convention)."

The implementation (`addons.py` line 31) and the test
(`test_addons_path_multi_path_repo_declaration_order_within_repo`, asserting
`primary_idx < secondary_idx`) both follow ARCHITECTURE.md — preserved order. The
spec example is wrong.

**What needs addressing:** correct the spec.md example so it matches the implemented
and tested behavior. The spec currently says reversed; both the code and the tests
say preserved. An agent implementing against the spec example will get this wrong.

---

## 5. `generate_instance_conf` returns a dict, not an ini string

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

## 6. `dbfilter` set before subdomain model ships

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

## 7. `ARCHIVE_CONFLICT` and `CONFIRMATION_REQUIRED` are undocumented error codes

---

## 8. `generate_instance_conf` is in `config.py`, not `instance.py`

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

## 9. `mcp.py` depends on `cli.py` — dependency direction is inverted

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

## 10. `find_conflicting_process` and `get_eviction_log` are permanent dead stubs

**Issue:** Two functions in `ports.py` have no implementation and no injection
parameter path that would ever exercise real behavior:

```python
def find_conflicting_process(port: int) -> dict | None:
    return None

def get_eviction_log(log_path: str) -> list[dict]:
    return []
```

Unlike other stubs where an injection parameter controls the path
(`simulate_failure=True` etc.), these functions have no parameter surface at all.
There is no test that passes a non-None result from `find_conflicting_process` —
the conflict detection path in `check_port_at_start` is exercised only by passing
`bound_by=` directly. The functions are exported from the module but never called
with real inputs anywhere.

This means the port-conflict-at-start flow (detecting which process holds a port,
surfacing its PID/name/cmdline) and the eviction log read path are completely
unexercised. These are load-bearing for the spec's "process name, PID, command
line" conflict surface.

**What needs addressing:** add injection parameters to both functions so the test
harness can exercise the callers that depend on them (`check_port_at_start`,
`eviction_count_in_window`), or document explicitly that these are integration-only
and note what the real implementation calls (e.g. `psutil`, `/proc`, `ss -tlnp`).

**Risk:** `errors.py` defines `ARCHIVE_CONFLICT` and `CONFIRMATION_REQUIRED` (lines
22–23) but neither appears in spec.md's error taxonomy table. An MCP consumer
receiving these codes has no documented semantics for how to handle them.

**What needs addressing:** add both codes to the spec.md error taxonomy table with
their meaning, trigger conditions, and expected consumer behavior.
