# Dashboard UI Proposal — Layout Revision

> Supersedes the "Layout" and "Settled > Centre" sections of `DASHBOARD-FRAMING.md`.
> All other framing decisions (notifications queue, header banner, onboarder model) hold.
> Status: agreed in principle, not yet implemented.

---

## What changes and why

The existing build has the centre pane dominating at ~60% width. Looking at it with real
fixture data, the centre content doesn't need that horizontal real estate — the detail cards
(Health, Scripts, Repos, Commands) are individually useful but don't need to be visible
simultaneously. You look at repo issues *or* port issues *or* script failures, not all at once.
Narrowing the centre and giving the right pane (logs) more space reflects actual usage.

---

## New layout proportions

```
┌─ owm ──────────── dev  ● running  dev.localhost  pid 12345  [Actions ▾] ─┐
│ Left (25%)         │  Centre (25%)              │  Right (50%)            │
│ INSTANCES          │  HTTP :8100 ✓  Gev :8101 ✓ │  Logs                   │
│ ● dev              │  DB dev ✓  Proxy ✓          │  [owm.log][dev][odoo…]  │
│ ○ feat-789         │  ────────────────────────── │                         │
│ ○ staging          │  Scripts: setup ok · fail ✗ │  …log output…           │
│                    │  ────────────────────────── │                         │
│ REMOTES            │  Repos: cc 3 behind ⚠       │                         │
│ odoo    2m         │  ────────────────────────── │                         │
│ cc      5m         │  psql · shell · logs · venv │                         │
│                    │                             │                         │
│ Processes          │                             │                         │
└────────────────────┴─────────────────────────────┴─────────────────────────┘
```

- **Left 25%** — instances list + remotes freshness + processes link. No change to content;
  "Repos" renamed to "Remotes" (see below).
- **Centre 25%** — per-instance status summary. Narrow by design; detail lives in modals.
- **Right 50%** — logs pane. Gets the majority of space since it's the primary working surface.

---

## Top navbar — instance docking

A persistent top navbar replaces the per-instance header that currently lives inside the centre
pane.

- **Wordmark only** when no instance is selected.
- **Instance context mounts** when you click an instance in the left nav:
  `dev  ● running  dev.localhost  pid 12345  [Actions ▾]`
- **Actions dropdown** contains Stop / Kill / Archive (and any future lifecycle actions).
  Moves destructive buttons out of the centre column, freeing vertical space and reducing
  misclick risk.
- Navbar is always visible; stays populated when a modal is open so you can switch instances
  without dismissing.

---

## Centre pane — summary rows, not full cards

Each section collapses to a single summary line. The summary is status-coloured and click-able.

| Section  | Summary format |
|----------|----------------|
| Health   | `HTTP :8100 ✓  Gevent :8101 ✓  DB dev ✓  Proxy dev.localhost ✓` |
| Scripts  | `setup ok · data-load ✗ · migrate —` |
| Repos    | `customer-config 3 behind ⚠ · enterprise ok · odoo ok` |
| Commands | `psql · shell · logs · venv` (click-to-copy pills, no command text shown) |

- **Commands becomes a quick-copy pill strip**, not a card. Labels only; the user knows what
  "psql" copies. No copy button clutter.
- **Section order**: Commands on top (steady-state happy-path, most reached for), then Health,
  Scripts, Repos. Matches `DASHBOARD-FRAMING.md` best-guess ordering.
- A ▸ chevron on each row opens the detail modal for that section.

---

## Detail modals — screen-wide, not inline accordions

Clicking a summary row (or its chevron) opens a **screen-wide modal** anchored below the navbar.

- Covers the centre and right panes; left nav stays visible so instance switching works without
  dismissing.
- Each section has its own modal: Health detail grid, Scripts table with Run buttons, Repos table
  with Sync buttons, Commands list with full command text and copy buttons.
- ESC / click-outside / close button dismisses.
- "Screen-wide" means the modal content gets the full width minus the left pane — roughly 75%.
  Repos table, in particular, benefits from this space.

---

## Right pane — log tabs

The log tab strip is instance-aware:

- **Auto-switches** to the selected instance's `instance.log` when you change instance in the
  left nav, unless a tab is pinned.
- **Available tabs** for the current instance: `instance.log`, `odoo.log`, plus one tab per
  recent script run result.
- **Pinning**: explicitly opened tabs stay open across instance switches.
- `owm.log` (workspace-level) is always available as a tab.

---

## Left nav rename

`REPOS` → `REMOTES`. The centre pane has a Repos section (per-instance worktree state); the left
nav section shows remote fetch freshness, which is workspace-level. Different data, different name.

---

## What this supersedes in DASHBOARD-FRAMING.md

| Old decision | Replaced by |
|---|---|
| Centre pane dominant (~60%) | Centre 25%; right pane 50% |
| Instance header + action buttons inside centre | Navbar docking; Actions dropdown |
| Full detail cards always visible | Summary rows by default; detail in screen-wide modals |
| "Centre re-order" as first landing step | Centre rewrite needed; modals are new infrastructure |
| Right pane proportions: open | Settled at ~50% |

The notifications queue, header banner, and onboarder model decisions are unchanged.
