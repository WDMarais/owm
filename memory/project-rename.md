---
name: project-rename
description: pyproject.toml distribution name is re-owm but should become owm once it supplants the old implementation
metadata:
  type: project
---

`pyproject.toml` has `name = "re-owm"` as the distribution name. The importable package (`src/owm/`) is already named correctly. The project name was kept as `re-owm` to avoid collision with the existing owm tool during development.

**Why:** Don't overwrite old owm until re-owm fully supplants it.

**How to apply:** When re-owm is production-ready, change `name = "re-owm"` to `name = "owm"` in pyproject.toml. One-liner. Flag it if the user asks about packaging, distribution, or entry points.
