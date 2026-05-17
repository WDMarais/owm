"""
Fixture data for live-derived state — stand-in for git calls, process scans,
and script result reads. dev_server.py imports from here; when real
implementations land these functions get replaced with actual I/O calls.
"""

REPO_FETCH_AGES: dict[str, str] = {
    "odoo":            "2026-05-18T10:22:28Z",
    "enterprise":      "2026-05-18T08:23:00Z",
    "customer-config": "2026-05-18T10:17:00Z",
}

INSTANCE_REPOS_SYNC: dict[str, dict] = {
    "dev": {
        "customer-config": {"behind_by": 3},
        "enterprise":      {},
        "odoo":            {},
    },
    "feat-789": {
        "customer-config": {"ahead_by": 2},
        "enterprise":      {},
        "odoo":            {"dirty": True},
    },
    "staging": {
        "customer-config": {"behind_by": 1, "ahead_by": 1},
        "enterprise":      {},
        "odoo":            {},
    },
}

INSTANCE_SCRIPTS: dict[str, dict] = {
    "dev": {
        "setup":     {"status": "ok",   "last_run_at": "2026-05-18T10:21:00Z"},
        "data-load": {"status": "fail", "last_run_at": "2026-05-18T10:09:00Z"},
        "migrate":   {"status": None,   "last_run_at": None},
    },
    "feat-789": {
        "setup":     {"status": "ok", "last_run_at": "2026-05-17T14:10:00Z"},
        "data-load": {"status": None, "last_run_at": None},
        "migrate":   {"status": None, "last_run_at": None},
    },
    "staging": {
        "setup": {"status": "ok", "last_run_at": "2026-05-16T09:04:00Z"},
    },
}
