---
name: harness-stub-bug
description: harness-writer pattern bug where stubs defined inside test function bodies can't be unwired without editing the test body
metadata:
  type: feedback
---

The harness-writer skill sometimes generates stubs inline inside test function bodies rather than at module level:

```python
def test_something():
    def some_fn(*args, **kwargs):  # stub defined inside test body
        raise NotImplementedError
    result = some_fn(...)
```

These shadow any module-level import with the same name and cannot be unwired without modifying the test body itself (not just adding an import).

**Why:** Spotted during re-owm implementation run — three tests in test_database_lifecycle.py had this pattern, as did all tests in test_error_taxonomy.py.

**How to apply:** When unwiring stubs, check whether the stub is at module level (can fix with import swap) or inside the test body (requires editing the test body to delete the stub function). If harness-writer is producing inline stubs, flag it immediately rather than deferring.
