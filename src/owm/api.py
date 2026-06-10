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
from owm.instance import (
    health_check,
    list_running_instances,
    owm_shaped_processes,
    scan_odoo_processes,
    classify_port_holder,
)
from owm.ports import find_conflicting_process, listeners_on_ports
from owm.sync import repo_alert_state
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
            classification = classify_port_holder(proc.get("cmdline"), workspace_root)
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
        s = repo_alert_state(wt, spec.branch, spec.base, spec.shared)
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


def _squatter_alert(instance: str, workspace_root: str) -> dict:
    port = load_instance_config(instance, workspace_root).server.http_port
    proc = find_conflicting_process(port)
    return {"instance": instance, "http_port": port,
            "pid": proc.get("pid") if proc else None,
            "classification": classify_port_holder(proc.get("cmdline") if proc else None,
                                                   workspace_root)}


def find_port_squatters(workspace_root: str) -> list[dict]:
    """Configured instances whose http_port is held by a process that isn't the
    instance's own tracked one — adopt-or-kill candidates. One net_connections
    snapshot across all configured ports, not a scan per instance. classification
    names what the holder is (owm-shaped orphan / foreign odoo / plain squatter)."""
    port_to_instance: dict[int, str] = {}
    for name in list_instances(workspace_root):
        try:
            port_to_instance[load_instance_config(name, workspace_root).server.http_port] = name
        except OwmError:
            continue
    managed = {m["instance"]: m["pid"] for m in list_running_instances(workspace_root)}
    squatters = []
    for port, holder in listeners_on_ports(set(port_to_instance)).items():
        instance = port_to_instance[port]
        if managed.get(instance) == holder["pid"]:
            continue  # the instance's own tracked process holds its port — not a squatter
        squatters.append({
            "instance": instance, "http_port": port, "pid": holder["pid"],
            "classification": classify_port_holder(holder["cmdline"], workspace_root),
        })
    return squatters


def odoo_ps(workspace_root: str) -> dict:
    """Every Odoo process on the host, classified for the status surface — managed,
    orphaned, foreign, squatters. managed/orphaned/foreign come from one cmdline walk
    (scan_odoo_processes), squatters from one socket snapshot (find_port_squatters).

    Tier precedence: an owm-shaped holder of a configured port is reported as an
    orphan, not a squatter; a foreign odoo that also squats one of our ports is
    reported only under squatters (more actionable than a bare foreign listing)."""
    running = list_running_instances(workspace_root)
    managed_instances = {r["instance"] for r in running}
    scan = scan_odoo_processes(workspace_root)
    orphaned = [p for p in scan["owm_shaped"] if p["instance"] not in managed_instances]
    squatters = [{"instance": s["instance"], "http_port": s["http_port"], "pid": s["pid"]}
                 for s in find_port_squatters(workspace_root)
                 if s["classification"] != "probable_orphan"]
    squatter_pids = {s["pid"] for s in squatters}
    foreign = [f for f in scan["foreign"] if f["pid"] not in squatter_pids]
    managed = [{"instance": r["instance"], "pid": r["pid"], "port": r["port"],
                "url": r["url"], "state": r["status"]} for r in running]
    return {"managed": managed, "orphaned": orphaned, "foreign": foreign, "squatters": squatters}


def find_orphaned_processes(workspace_root: str) -> list[dict]:
    """owm-shaped processes owm isn't managing — configured for an instance that
    isn't a currently-tracked running instance (deleted instance still up, leaked
    process, stale state). Complements find_port_squatters: that finds non-owm
    processes on a known instance's port; this finds owm-shaped odoo off the grid."""
    managed = {i["instance"] for i in list_running_instances(workspace_root)}
    return [p for p in owm_shaped_processes(workspace_root)
            if p["instance"] not in managed]


def _scan_instance(entry, workspace_root: str):
    """Process one instance entry. Returns (name, inst_dict, health, alerts, warning).

    inst_dict and health are None when the entry is skipped (orphan dir, bad toml).
    Never raises — a single bad instance must not abort the workspace scan.
    """
    name = entry.name
    toml_path = os.path.join(entry.path, "instance.toml")
    if not os.path.exists(toml_path):
        return name, None, None, [], {"type": "orphan_dir", "path": f"instances/{name}"}
    try:
        with open(toml_path) as f:
            conf = parse_instance_config(f.read())
    except Exception:
        return name, None, None, [], None
    h = health_check(name, workspace_root)
    inst: dict = {"state": h.status}
    if h.pid:
        inst["pid"] = h.pid
    if h.url:
        inst["url"] = h.url
    inst["local_url"] = f"http://localhost:{conf.server.http_port}"
    return name, inst, h, _repo_alerts(name, conf, workspace_root), None


def workspace_status(workspace_root: str) -> dict:
    instances_dir = os.path.join(workspace_root, "instances")
    instances = {}
    repo_alerts = []
    workspace_warnings = []
    health_by_instance: dict = {}

    try:
        entries = [
            e for e in os.scandir(instances_dir)
            if e.is_dir() and not e.name.startswith(("_", "."))
        ]
    except OSError:
        return {"instances": {}, "repo_alerts": [], "port_alerts": [], "unmanaged_odoo": [], "workspace_warnings": []}

    for entry in entries:
        name, inst, h, alerts, warning = _scan_instance(entry, workspace_root)
        if warning:
            workspace_warnings.append(warning)
        if inst is not None:
            instances[name] = inst
            repo_alerts.extend(alerts)
            health_by_instance[name] = h

    unmanaged_odoo = find_orphaned_processes(workspace_root)

    port_alerts = [
        _squatter_alert(name, workspace_root)
        for name, h in health_by_instance.items()
        if h.status == "unmanaged"
    ]

    return {
        "instances": instances,
        "repo_alerts": repo_alerts,
        "port_alerts": port_alerts,
        "unmanaged_odoo": unmanaged_odoo,
        "workspace_warnings": workspace_warnings,
    }
