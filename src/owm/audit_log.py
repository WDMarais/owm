import json
import os
from datetime import datetime, timezone


def append_log_entry(
    log_path: str,
    operation: str,
    instance: str,
    result: str,
    *,
    pid: int | None = None,
    source: str | None = None,
    summary: dict | None = None,
    script: str | None = None,
    dashboard_open: bool = True,
) -> dict:
    entry: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operation": operation,
        "instance": instance,
        "result": result,
    }
    if pid is not None:
        entry["pid"] = pid
    if source is not None:
        entry["source"] = source
    if summary is not None:
        entry["summary"] = summary
    if script is not None:
        entry["script"] = script

    try:
        parent = os.path.dirname(log_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass

    return entry


def read_log_tail(log_path: str, n: int) -> list[dict]:
    try:
        with open(log_path) as f:
            lines = f.readlines()
    except OSError:
        return []

    tail = lines[-n:] if n < len(lines) else lines
    result = []
    for line in tail:
        line = line.strip()
        if line:
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return result


def parse_log_entry(raw: str) -> dict:
    return json.loads(raw)
