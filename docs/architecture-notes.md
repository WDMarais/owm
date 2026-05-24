# Architecture notes

Working decisions and known future refactors. Not prescriptive — update as understanding improves.

---

## Structured output layer (`owm.mcp` → `owm.api`)

**Current state:** `owm.mcp` is named after its first consumer (the MCP tool surface) but is really a general structured-output layer — it calls library modules and assembles JSON-serialisable dicts. The CLI currently calls library modules directly and renders prose itself.

**Problem:** Once the CLI gains a `--json` flag, both it and the MCP layer will need the same structured dicts. Duplicating that assembly in two places (or having `cli.py` import from `owm.mcp`) is wrong.

**Intended shape:**
```
owm.api   — structured output layer; returns typed dicts, no prose, no transport concerns
owm.mcp   — thin wrapper: MCP tool signatures → owm.api calls
owm.cli   — no --json: formats owm.api output as prose
            --json: passes owm.api output through directly
```

`owm.mcp` becomes mostly glue. All classification logic, alert assembly, `suspected_linked`, `workspace_warnings` etc. live in `owm.api`.

**When to do it:** Once the MCP/CLI surface is more complete and the shape of `owm.api` is stable enough to name cleanly. Premature rename just creates churn.
