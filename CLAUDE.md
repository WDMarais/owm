# re-owm

Spec-first rewrite of owm. Portfolio context, identity/isolation, and the
env-var spine live in `~/proj/CLAUDE.md` — read that first.

## Running commands
This is a **uv** project (`uv.lock` is committed). Run everything through `uv`
so it syncs from the lockfile and uses the project venv. Do **not** invoke
`.venv/bin/python` directly — it bypasses the sync-from-lock guarantee.

- Tests: `uv run pytest -q`
- Scripts / REPL: `uv run python ...`
- Add a dependency: `uv add <pkg>` (runtime) or `uv add --dev <pkg>` (dev group)
