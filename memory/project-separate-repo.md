---
name: project-separate-repo
description: re-owm is intentionally a separate repo from owm, not a branch — clean public provenance
metadata:
  type: project
---

re-owm is kept as a separate repo rather than a branch on owm.

**Why:** owm accumulated company-specific references and other things that make it hard to publish cleanly. re-owm starts with no such history and can be made public or shared without a scrubbing pass. Merging owm history (even as an orphan branch) would import that baggage.

**How to apply:** don't suggest migrating re-owm onto the owm repo. Keep them separate until owm is eventually retired/replaced. The transition path is a new release from re-owm, not a merge.
