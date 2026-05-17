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
