# Dashboard framing

> Status: design decisions for re-owm dashboard work. Captured ahead of implementation
> to avoid re-deriving conclusions when work resumes. Read before adding dashboard
> pages or restructuring panes; the framing here applies across all of them.
>
> Prereq for most "Open" items: re-owm backend wired to real state. Mocked-state work
> is a poor venue for validating UI frictions — those items are deferred for that
> reason. The "Settled" decisions are the exception: they're about the *static
> skeleton* (HTML structure, layout, what each pane is *for*), which is safe to land
> without real state and pays compounding dividends — every future page inherits a
> sensible foundation.

---

## What the dashboard is for

The dashboard competes with the terminal, not with "no information." `owm status`,
`owm logs --follow`, `ps aux | grep odoo`, `psql` already exist and are good. The
dashboard earns its place only where the terminal is genuinely bad:

- **Glanceability** — peripheral awareness while working on something else
- **Multi-state-at-once** — "is feat-789 healthy AND staging AND fetch fresh" in one look
- **Click-to-pivot** — "this looks broken → show me its logs → run its setup" without typing commands
- **Persistent monitoring** of streams (logs, events, in-progress operations)
- **Token reduction** for agent-mediated workflows — surfacing state that would otherwise prompt "let me ask Claude what's happening"

This **deprioritises**:

- Static one-shot lookups (CLI is faster)
- Rich log search/filter (`grep` wins; dashboard log viewer is for "what's happening now," not "find that error from yesterday")
- Anything needing arbitrary input/config (stays in CLI/agent)
- Replicating `owm status` text verbatim — that's a worse terminal

The dashboard **inherits** owm's existing philosophy: deliberate ceilings (no
`--force` escape hatches), terse defaults, opinions encoded as refusals.

---

## Settled

Constraint-driven decisions; changing them requires reversing a stated premise.

### Layout

- **Three-pane (left / centre / right) holds.** Fixed structure, no priority-stacking-mode.
- **Left pane = workspace territory** (instances/repos inventory + notifications queue).
- **Centre pane = currently-selected instance's operating surface** (fixed section order, doesn't shift dynamically).
- **Right pane = logs**, stays right; proportions open (see below).
- **No mode toggles, no priority-stacking opt-in, no expert-vs-beginner switch.** Modes have a real cost (designed twice, persisted state, mental model fork) and contradict the single-archetype model below.

### Notifications queue (left-pane bottom)

- **Workspace-wide scope.** Shows every instance's issues with `[instance]` prefix per row, not just the currently selected one.
- **State, not events.** Queue reflects current state; not a history log.
- **Auto-clear on state resolution.** No manual dismissal. Fix the thing → entry disappears.
- **Reactive only.** No browser notifications, sound, tab-title-change, or other pushy mechanisms.
- **Urgency tiers** (hard-coded, tune from real usage):
  - **Blocking** (red): instance crashed, port squatter on running instance, divergence needing rebase
  - **Attention** (yellow): script failed, dirty repo, stale fetch
  - **Active** (blue): script running, instance starting, fetch in progress
- **Ordering**: urgency-tier first, newest-first within tier.
- **Click behaviour (full pivot)**: switch instance if needed → scroll centre to relevant section → 1-second subtle background-colour shift. No flash/pulse/animation library.
- **Excludes**: healthy/clean state, successful operations (those go inline at the action surface), purely informational content.
- **Script runs replace each other** — latest run only; regression-detector logic means >3 runs ago is noise.

Approximate visual (severity dot + `[instance]` + short description, whole row is click target):

```
🔴 [feat-789]   port 8142 squatted by python3
🔴 [staging]    diverged — rebase needed
🟡 [feat-789]   Scripts: data-load failed
🟡 [staging]    fetched 4d ago
🔵 [review-101] starting…
```

### Header banner (new — currently missing from build)

- **Reserved for workspace-critical conditions only**: PSQL cluster down, disk full, port range exhausted, workspace.toml unparseable, base template missing.
- **Architecturally above the queue** — these issues mean the entire dashboard is showing degraded info; user needs to see them before engaging with any instance.
- **Minimal when no condition met** — workspace name, maybe a global fetch button. Dominates when present.
- **Not the same as queue's red tier.** Queue red = "this instance is broken." Header red = "the whole system is broken." Different scope, different surface.

### Onboarder model (urban-planning, not training-wheels)

- **Single archetype across expertise levels.** The tool stays consistent; the user grows in their understanding of the underlying domain (Odoo, git, worktrees) independently of the tool. The tool is a legible artifact of the domain, not a tutor for it.
- **Tooltips/help are reference, not tutorial.** A `?` icon → one-liner explanation. No coachmarks, no first-run tours, no "you might be wondering about..." popovers.
- **Defaults stay terse always.** "Sync", not "Sync (recommended for...)". Behaviour is the documentation.
- **Confirmation on destructive ops** regardless of expertise — kill, archive, force-reset, db-restore. Not because the user doesn't know; because anyone can misclick.
- **Deliberate ceilings are the real onboarder protection.** No `--force` escape hatches in the dashboard. If you need that, you're already off the bicycle and into raw git/psql. Feature, not limitation.

---

## Best-guess

Judgment calls; real usage will likely tune them.

- **Centre's fixed order**: Commands on top (most-used in steady-state-healthy), then Health, Scripts, Repos. Assumes happy-path-dominant usage; revisit if real users check Health first more often.
- **Urgency-tier assignment**: the categories themselves should hold; *which condition lands in which tier* will probably get refined as real conditions surface (e.g., is "fetched 4d ago" attention or just ambient?).
- **Click-pivot subtle-colour-shift**: 1-second background change may add little over just-scroll. If implementation cost is non-trivial, drop to scroll-only.
- **"Last script run sticks until next replaces it"**: alternative is auto-clear after N minutes (toast pattern). Stick-until-replaced feels right for regression detectors but might be wrong for one-off scripts.

---

## Open

Deferred until re-owm backend → dashboard reads real state.

- **Right pane (logs) proportions.** Currently ~20%, too narrow for log line widths. ~50% was proposed; right answer depends on what log volume and typical line lengths look like with real instances.
- **The actual next dashboard page after framing lands.** Workspace-overview-style content may be partly absorbed by header + queue; audit-log page may become more valuable; or something else may emerge. Re-ask once header + queue + centre-reorder are real.
- **Whether the header banner needs sub-tiers** (warning vs blocker). Single-tier may be enough; revisit if workspace-level conditions accumulate variety.
- **State caching/staleness model** for the dashboard surface — see `INCOMING.md` § "State caching and staleness model." Affects refresh semantics, polling vs SSE, what's "live" vs cached.

---

## Suggested landing order (when dashboard work resumes)

1. **Centre re-order** — smallest change, biggest immediate steady-state win. ~half day.
2. **Header banner** — needs a list of workspace-critical conditions + a banner component + state-derivation. Bounded scope.
3. **Notifications queue** — biggest design surface (visual treatment, click-to-pivot, scroll/highlight), highest-value addition.

Each is independently shippable; landing them in order raises the floor for any subsequent page.

---

## Bookmarks for owm-server (out of scope here, but related)

- **Push notifications** belong in real pager integration (PagerDuty/OpsGenie), not browser pings. The local "reactive only" decision is correct *because* crashes on the instance you're using are self-evident. Server context inverts this — top-priority customer offline while you're doing busywork on another tenant is a genuine push case. But that's paging infra, not dashboard UI.

---

## Cross-references

- `spec.md` § Dashboard — original spec, marked superseded but contains the layout/contents starting point
- `INCOMING.md` — state caching design questions still open
- `IMPLEMENTATION-NOTES.md` — `DashboardState` type noted as needing definition before MCP layer
