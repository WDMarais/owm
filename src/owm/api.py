"""
Structured output layer — returns JSON-serialisable dicts, no prose, no transport concerns.
Consumed by owm.mcp (MCP tool surface) and owm.cli (--json flag, and prose formatting).
"""
import os

from owm.config import parse_instance_config
from owm.errors import format_error
from owm.instance import health_check
from owm.ports import find_conflicting_process


def default_workspace() -> str:
    """Return OWM_WORKSPACE env var if set, otherwise '.'."""
    return os.environ.get("OWM_WORKSPACE", ".")


def instance_status(instance: str, workspace_root: str) -> dict:
    toml_path = os.path.join(workspace_root, "instances", instance, "instance.toml")
    try:
        with open(toml_path) as f:
            conf = parse_instance_config(f.read())
    except OSError:
        return format_error(f"instance {instance!r} not found", "NOT_FOUND")

    h = health_check(instance, workspace_root)
    http_port = conf.server.http_port

    suspected_linked = None
    if h["status"] in ("stopped", "unmanaged"):
        proc = find_conflicting_process(http_port)
        if proc:
            if "odoo-bin" in proc.get("cmdline", "") or instance in proc.get("cmdline", ""):
                classification = "probable_orphan"
            else:
                classification = "probable_squatter"
            suspected_linked = {"classification": classification, **proc}

    return {
        "instance": instance,
        "state": h["status"],
        "http_port": http_port,
        "local_url": f"http://localhost:{http_port}",
        "url": h.get("url"),
        "db": conf.database.name,
        "pid": h.get("pid"),
        "suspected_linked": suspected_linked,
    }


def workspace_status(workspace_root: str) -> dict:
    instances_dir = os.path.join(workspace_root, "instances")
    instances = {}
    port_alerts = []
    workspace_warnings = []

    try:
        entries = list(os.scandir(instances_dir))
    except OSError:
        return {"instances": {}, "repo_alerts": [], "port_alerts": [], "unmanaged_odoo": [], "workspace_warnings": []}

    for entry in entries:
        if not entry.is_dir():
            continue
        if entry.name.startswith("_") or entry.name.startswith("."):
            continue
        toml_path = os.path.join(entry.path, "instance.toml")
        if not os.path.exists(toml_path):
            workspace_warnings.append({"type": "orphan_dir", "path": f"instances/{entry.name}"})
            continue
        try:
            with open(toml_path) as f:
                conf = parse_instance_config(f.read())
        except Exception:
            continue
        h = health_check(entry.name, workspace_root)
        inst: dict = {"state": h["status"]}
        if h.get("pid"):
            inst["pid"] = h["pid"]
        if h.get("url"):
            inst["url"] = h["url"]
        inst["local_url"] = f"http://localhost:{conf.server.http_port}"
        instances[entry.name] = inst

        if h["status"] == "unmanaged":
            proc = find_conflicting_process(conf.server.http_port)
            port_alerts.append({
                "instance": entry.name,
                "http_port": conf.server.http_port,
                "pid": h.get("pid"),
                "classification": "probable_orphan" if proc and "odoo-bin" in proc.get("cmdline", "") else "probable_squatter",
            })

    return {
        "instances": instances,
        "repo_alerts": [],
        "port_alerts": port_alerts,
        "unmanaged_odoo": [],
        "workspace_warnings": workspace_warnings,
    }
