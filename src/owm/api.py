"""
Structured output layer — returns JSON-serialisable dicts, no prose, no transport concerns.
Consumed by owm.mcp (MCP tool surface) and owm.cli (--json flag, and prose formatting).
"""
import os

from owm.config import parse_instance_config, load_instance_config
from owm.errors import OwmError, format_error
from owm.instance import health_check
from owm.ports import find_conflicting_process
from owm.sync import repo_sync_status
from owm.worktrees import resolve_worktree_path


def default_workspace() -> str:
    """Return OWM_WORKSPACE env var if set, otherwise '.'."""
    return os.environ.get("OWM_WORKSPACE", ".")


def instance_status(instance: str, workspace_root: str) -> dict:
    try:
        conf = load_instance_config(instance, workspace_root)
    except OwmError as e:
        return format_error(str(e.args[0]), str(e.code))

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


def workspace_status(workspace_root: str) -> dict:
    instances_dir = os.path.join(workspace_root, "instances")
    instances = {}
    repo_alerts = []
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
        repo_alerts.extend(_repo_alerts(entry.name, conf, workspace_root))

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
        "repo_alerts": repo_alerts,
        "port_alerts": port_alerts,
        "unmanaged_odoo": [],
        "workspace_warnings": workspace_warnings,
    }
