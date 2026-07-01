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

---

## Script env injection — `[scripts.env]` + `env_file` (2026-06-22)

re-owm has no script-env concept at all yet. `execute_script` (`scripts.py`) runs the
runner subprocess with the bare instance venv and inherited process env — no per-instance
env merge — and `InstanceScripts` (`config.py`) has no `env`/`env_file` field. owm grew an
`env_file` feature (gitignored dotenv merged into the script env, on top of inline
`[scripts.env]`) on 2026-06-22; re-owm should spec the whole concept, with `env_file` as its
first form, rather than port owm's implementation.

Use case: script credentials (service users, API tokens, host endpoints) that shouldn't sit
in a TOML that tools read or logs capture. Put them in a gitignored file instead.

Design questions to resolve in spec.md (Script tools / instance config schema):
- **Merge order + precedence.** owm's is: process env → `[scripts.env]` (inline) → `env_file`
  (file keys override inline). Confirm that's the right precedence for re-owm.
- **Reserved namespace.** owm rejects any `OWM_*` key from either source so script env can't
  shadow the injected `OWM_*` contract. re-owm's contract vars differ (`DB_NAME`/`HTTP_PORT`/…)
  — decide which prefix(es) are reserved and whether the guard is an error or a warning.
- **File format.** owm uses a minimal hand-rolled dotenv (`KEY=VALUE`, `#` comments, optional
  `export `, quoted values, no interpolation) to avoid a python-dotenv dep. Match, or adopt a
  library? Define resolution (relative-to-instance vs absolute) and missing-file behaviour
  (owm: hard error).
- **Surface scope.** Applies to `owm_run_script` and `owm_compare` (both spawn runners). Does
  it also touch any other subprocess surface (seed scripts on `db-reset`)?
- **Spec a second shape?** The original idea also floated `env_from = "<shell expr>"` (source
  the output of a command, for keychains/vaults). Deferred in owm; decide if re-owm specs it.

---

## Branch expected-state marker + fetch resilience (2026-07-01)

### What surfaced it
`owm create cd-2117` failed `BRANCH_NOT_FOUND` for a branch that *does* exist on origin,
while `owm fetch` reported the repo "up to date". Root cause: `git fetch` aborts the whole
invocation on the first missing refspec, so one stale/never-pushed branch named in *any*
instance.toml poisoned the entire repo's batched fetch, and the non-zero exit was swallowed
as "nothing to update". A later create for a valid-but-unfetched branch then failed.

Fixed in the rewrite (two commits, unpushed as of writing): `git_fetch_bare` now raises
`FETCH_FAILED` instead of returning False on non-zero exit; `fetch_active_branches`
prefilters declared branches against `ls-remote` and only fetches those on origin. A dropped
branch is reported "missing" only when absent from origin *and* local (a real broken ref);
present-locally-but-not-on-origin is a normal unpushed / merged-then-deleted working branch.

### The design question
Branch intent is currently implicit in flags: `+create` = "not made yet, create from base";
`+exists` = "must already exist"; default = "exists somewhere". The audit's ambiguity —
*is a missing-from-origin branch unpushed, merged-then-deleted, or a typo?* — exists only
because intent isn't declared. Proposal: generalize into one explicit per-repo `expect`
(name TBD): `upstream` (on origin; fetch/track; error if absent) · `local` (unpushed/kept
local; skip fetch, no warn) · `new` (= `+create`; must not exist; create from base) · `any`
(default = today's origin-vs-local heuristic). Additive, back-compatible; the heuristic stays
as the unmarked default. Subsumes the hand-set "PR merged, branch deleted" marker — that's
just the lifecycle transition `upstream → local`.

### Legacy prior art (owm-legacy) — the rewrite regressed this
Legacy already had both the fetch fix and a state model. Worth mining before speccing:

- **Fetch resilience** (`cmd_repo.py:_fetch_bare_repo`): *optimistic* — tries the combined
  fetch first, and only on failure runs `ls-remote` to find which branches are missing, then
  retries with the present ones ("so one deleted branch doesn't block the rest"). The rewrite
  instead *always* prefilters (ls-remote first). Tradeoff: legacy = one round trip on the happy
  path; rewrite = simpler, always two. Consider adopting legacy's optimistic-then-repair shape.
- **Refspec namespace inconsistency (latent rewrite bug).** Legacy fetches
  `+refs/heads/{b}:refs/remotes/origin/{b}` (proper remote-tracking refs), consistent with its
  `remote_ref_exists`/tracking checks. The rewrite's *targeted* `git_fetch_bare` maps to
  `refs/heads/{b}` while its *full* fetch uses `refs/remotes/origin/*` — so targeted-fetched
  branches land as local branches, and create's `_origin_branch_exists` (checks
  `refs/remotes/origin/`) can miss them. Normalize the rewrite to `refs/remotes/origin/*`.
- **Derived state flags** (written to legacy `instance-state.json` by
  `_update_not_on_remote`, cmd_repo.py:472; cleared on push; surfaced in `collect.py` status):
  - `not_on_remote[repo] = branch` — attempted and missing on remote.
  - `no_upstream_tracking[repo] = "fixable"` (origin/<branch> exists but no local tracking →
    run repair-tracking) `| "no_origin_ref"` (no origin ref at all — never pushed / deleted).

### Key distinction for the spec
Legacy's flags are **derived/observed** state (recomputed each fetch, descriptive). The
`expect` marker is **declared intent** (prescriptive). The rich design keeps both and
*reconciles* them: declared `upstream` + observed not-on-remote → warn "push it or mark
local"; declared `local` + now-on-origin → suggest promote; declared `new` + exists → error
(today's `+create` check). That reconciliation is exactly the merged-and-deleted detection.

Open questions: field name/values; do `+create`/`+exists` become sugar for `expect`; does
`shared` imply `upstream`; revive observed-state storage (legacy's flags into `state.json`)
vs compute-on-demand; where reconciliation warnings live (`fetch` vs `validate`).
