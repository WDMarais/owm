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

def _sync(*, dirty=False, vob_a=0, vob_b=0, vobase_a=0, vobase_b=0, obvobase_a=0, obvobase_b=0):
    return {
        "dirty":                    dirty,
        "vs_origin_branch":         {"ahead_by": vob_a,      "behind_by": vob_b},
        "vs_origin_base":           {"ahead_by": vobase_a,   "behind_by": vobase_b},
        "origin_branch_vs_origin_base": {"ahead_by": obvobase_a, "behind_by": obvobase_b},
    }

INSTANCE_REPOS_SYNC: dict[str, dict] = {
    "dev": {
        "customer-config": _sync(vob_b=3),
        "enterprise":      _sync(),
        "odoo":            _sync(),
    },
    "feat-789": {
        "customer-config": _sync(vob_a=2, vobase_b=1, obvobase_a=2, obvobase_b=1),
        "enterprise":      _sync(),
        "odoo":            _sync(dirty=True),
    },
    "staging": {
        "customer-config": _sync(vob_a=1, vob_b=1, vobase_b=2, obvobase_b=2),
        "enterprise":      _sync(),
        "odoo":            _sync(),
    },
}

PROCESSES: dict = {
    "managed": [
        {"name": "dev",     "pid": 12345, "ports": [8100, 8101]},
        {"name": "staging", "pid": 18833, "ports": [8106, 8107]},
    ],
    "orphaned": [
        {"name": "feat-123", "pid": 9981, "ports": [8102, 8103]},
    ],
    "unregistered": [
        {"pid": 7732, "ports": [8104, 8105], "cmd": "python odoo-bin --http-port 8104 -d feat_789"},
    ],
    "squatters": [
        {"pid": 4421, "ports": [8108], "cmd": "python3 manage.py runserver 0.0.0.0:8108"},
    ],
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
