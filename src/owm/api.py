"""
Structured output layer — returns JSON-serialisable dicts, no prose, no transport concerns.
Consumed by owm.mcp (MCP tool surface) and owm.cli (--json flag, and prose formatting).
"""
import os

from owm.config import (
    parse_instance_config,
    load_instance_config,
    list_instances,
    resolve_workspace_root,
)
from owm.errors import OwmError, format_error
from owm.instance import health_check, list_running_instances, owm_shaped_processes
from owm.ports import find_conflicting_process
from owm.sync import repo_sync_status
from owm.worktrees import resolve_worktree_path


def default_workspace() -> str:
    """Resolve the workspace root for api/mcp callers that didn't supply one.

    Thin wrapper over the shared resolver (OWM_WORKSPACE, else walk up from cwd)
    so api/mcp use the same precedence as the CLI. No override here — callers pass
    an explicit workspace_root when they have one (`workspace_root or
    default_workspace()`). Raises OwmError(NOT_FOUND) when nothing resolves rather
    than silently defaulting to '.'."""
    return resolve_workspace_root()


def instance_status(instance: str, workspace_root: str) -> dict:
    try:
        conf = load_instance_config(instance, workspace_root)
    except OwmError as e:
        return format_error(str(e.args[0]), str(e.code))

    h = health_check(instance, workspace_root)
    http_port = conf.server.http_port

    suspected_linked = None
    if h.status in ("stopped", "unmanaged"):
        proc = find_conflicting_process(http_port)
        if proc:
            if "odoo-bin" in proc.get("cmdline", "") or instance in proc.get("cmdline", ""):
                classification = "probable_orphan"
            else:
                classification = "probable_squatter"
            suspected_linked = {"classification": classification, **proc}

    return {
        "instance": instance,
        "state": h.status,
        "http_port": http_port,
        "local_url": f"http://localhost:{http_port}",
        "url": h.url,
        "db": conf.database.name,
        "pid": h.pid,
        "suspected_linked": suspected_linked,
    }


def _repo_alerts(instance: str, conf, workspace_root: str) -> list:
    """Per-repo states worth flagging in workspace status, via the shared git
    reader. Shared repos are read-only by convention (surfaced through fetch,
    not here); ahead-only is normal feature work, not an alert."""
    alerts = []
    for repo, spec in conf.repos.items():
        if spec.shared:
            continue
        wt = resolve_worktree_path(repo, spec.branch, spec.shared, workspace_root, instance).path
        s = repo_sync_status(wt, spec.branch, spec.base, spec.shared)
        vob = s["vs_origin_branch"]
        if s["dirty"]:
            alerts.append({"instance": instance, "repo": repo, "issue": "dirty"})
        if vob["behind_by"] and vob["ahead_by"]:
            alerts.append({"instance": instance, "repo": repo, "issue": "diverged",
                           "ahead_by": vob["ahead_by"], "behind_by": vob["behind_by"]})
        elif vob["behind_by"]:
            alerts.append({"instance": instance, "repo": repo, "issue": "behind",
                           "behind_by": vob["behind_by"]})
        if s["origin_branch_vs_origin_base"]["behind_by"]:
            alerts.append({"instance": instance, "repo": repo, "issue": "base_behind",
                           "behind_by": s["origin_branch_vs_origin_base"]["behind_by"]})
    return alerts


def _holder_classification(proc: dict | None) -> str:
    if proc and "odoo-bin" in (proc.get("cmdline") or ""):
        return "probable_orphan"
    return "probable_squatter"


def _squatter_alert(instance: str, workspace_root: str) -> dict:
    port = load_instance_config(instance, workspace_root).server.http_port
    proc = find_conflicting_process(port)
    return {"instance": instance, "http_port": port,
            "pid": proc.get("pid") if proc else None,
            "classification": _holder_classification(proc)}


def find_port_squatters(workspace_root: str) -> list[dict]:
    """Configured instances whose port a non-owm process holds — adopt-or-kill
    candidates. health_check is the canonical port+pid check; "unmanaged" means a
    process owm isn't tracking holds the port. CLI, MCP, and dashboard route here."""
    return [
        _squatter_alert(name, workspace_root)
        for name in list_instances(workspace_root)
        if health_check(name, workspace_root).status == "unmanaged"
    ]


def find_orphaned_processes(workspace_root: str) -> list[dict]:
    """owm-shaped processes owm isn't managing — configured for an instance that
    isn't a currently-tracked running instance (deleted instance still up, leaked
    process, stale state). Complements find_port_squatters: that finds non-owm
    processes on a known instance's port; this finds owm-shaped odoo off the grid."""
    managed = {i["instance"] for i in list_running_instances(workspace_root)}
    return [p for p in owm_shaped_processes(workspace_root)
            if p["instance"] not in managed]


def workspace_status(workspace_root: str) -> dict:
    instances_dir = os.path.join(workspace_root, "instances")
    instances = {}
    repo_alerts = []
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
        inst: dict = {"state": h.status}
        if h.pid:
            inst["pid"] = h.pid
        if h.url:
            inst["url"] = h.url
        inst["local_url"] = f"http://localhost:{conf.server.http_port}"
        instances[entry.name] = inst
        repo_alerts.extend(_repo_alerts(entry.name, conf, workspace_root))

    return {
        "instances": instances,
        "repo_alerts": repo_alerts,
        "port_alerts": find_port_squatters(workspace_root),
        "unmanaged_odoo": find_orphaned_processes(workspace_root),
        "workspace_warnings": workspace_warnings,
    }
