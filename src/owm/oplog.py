"""
Operational logging: structured NDJSON to owm.log, plain separators to instance logs.
"""
import json
import os
from datetime import datetime, timezone


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def workspace_log(workspace_root: str, event: str, **fields) -> None:
    """Append one NDJSON line to owm.log."""
    entry = {"ts": _ts(), "event": event, **fields}
    log_path = os.path.join(workspace_root, "owm.log")
    with open(log_path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def instance_separator(log_path: str, message: str) -> None:
    """Write a human-readable session boundary line to an instance log."""
    line = f"=== owm: {message} {_ts()} ===\n"
    with open(log_path, "a") as f:
        f.write(line)
