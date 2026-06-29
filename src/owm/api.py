"""
Structured output layer — returns JSON-serialisable dicts, no prose, no transport concerns.
Consumed by owm.mcp (MCP tool surface) and owm.cli (--json flag, and prose formatting).
"""
import json
import os
from datetime import datetime, timezone

from owm.config import (
    parse_instance_config,
    parse_workspace_config,
    load_instance_config,
    list_instances,
    resolve_workspace_root,
)
from owm.errors import OwmError, format_error, NO_COMPARE_TARGET, NOT_FOUND
from owm.instance import (
    health_check,
    list_running_instances,
    owm_shaped_processes,
    scan_odoo_processes,
    classify_port_holder,
    module_install_status,
)
from owm.ports import find_conflicting_process, listeners_on_ports, plan_ports
from owm.sync import repo_alert_state, git_run
from owm.scripts import execute_script, run_script, compare_instances
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
    snapshot across all configured ports, not a scan per instance. `instance` is
    the victim (the configured owm instance whose port is taken); `name`/`cmdline`
    identify the holder doing the squatting; `classification` names what the holder
    is (owm-shaped orphan / foreign odoo / plain squatter)."""
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
            "name": holder["name"], "cmdline": holder["cmdline"],
            "classification": classify_port_holder(holder["cmdline"], workspace_root),
        })
    return squatters


def next_ports(workspace_root: str, count: int = 1) -> dict:
    """Lowest free http/gevent port pair(s) in the workspace range — a read-only
    preview of what create/start would grab. Scans instances/ for occupied ports,
    reads the range from workspace defaults, and reports the next pair(s) plus
    warnings on odd or colliding allocations. No process scan; config-derived only."""
    with open(os.path.join(workspace_root, "workspace.toml")) as f:
        ws = parse_workspace_config(f.read())
    port_range = ws.defaults.http_port_range

    allocations = []
    for name in list_instances(workspace_root):
        try:
            conf = load_instance_config(name, workspace_root)
        except OwmError:
            continue
        allocations.append({"instance": name,
                            "http_port": conf.server.http_port,
                            "gevent_port": conf.server.gevent_port})

    plan = plan_ports(allocations, port_range, count=count)
    nxt = plan.candidates[0] if plan.candidates else None
    return {
        "range": list(port_range),
        "next": {"http_port": nxt.http_port, "gevent_port": nxt.gevent_port} if nxt else None,
        "candidates": [{"http_port": p.http_port, "gevent_port": p.gevent_port}
                       for p in plan.candidates],
        "free_pairs": plan.free_pairs,
        "nominal_pairs": plan.nominal_pairs,
        "warnings": plan.warnings,
    }


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
    squatters = [{"instance": s["instance"], "http_port": s["http_port"], "pid": s["pid"],
                  "name": s["name"], "cmdline": s["cmdline"]}
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


def check_modules(instance: str, workspace_root: str) -> dict:
    """Which configured [install] modules are actually installed in the instance DB.

    {instance, installed, missing} on success; {instance, note} when no modules
    are declared; {instance, error: "db_unreachable"} when the DB can't be queried.
    """
    conf = load_instance_config(instance, workspace_root)
    modules = conf.install.modules if conf.install else []
    if not modules:
        return {"instance": instance, "installed": [], "missing": [], "note": "no modules in [install]"}
    status = module_install_status(conf.database.name, conf.database.pg_port, modules)
    if status is None:
        return {"instance": instance, "error": "db_unreachable"}
    installed, missing = status
    return {"instance": instance, "installed": installed, "missing": missing}


def instance_diff(instance: str, workspace_root: str, mode: str = "patch") -> dict:
    """Per-repo diff (base...branch) for an instance's feature worktrees.

    `mode` selects the heavy payload, but every repo entry always carries the
    cheap {branch, base, files, modules} (top-level dir of each changed path =
    the affected addon) so callers can summarise regardless of mode:
      - "patch"     (default): adds "diff", the full unified patch
      - "name-only": files/modules only, no extra git call
      - "stat"      : adds "stat", the diffstat text
    Repos with no base configured or a missing worktree are reported with a
    "skipped" reason; git failures with an "error".
    """
    conf = load_instance_config(instance, workspace_root)
    repos: dict = {}
    for repo_name, spec in conf.repos.items():
        if not spec.base:
            repos[repo_name] = {"branch": spec.branch, "base": None, "skipped": "no base configured"}
            continue
        wt = resolve_worktree_path(repo_name, spec.branch, spec.shared, workspace_root, instance).path
        if not os.path.isdir(wt):
            repos[repo_name] = {"branch": spec.branch, "base": spec.base, "skipped": "worktree not found"}
            continue
        rng = f"{spec.base}...{spec.branch}"
        name_only = git_run(["diff", "--name-only", rng], cwd=wt, check=False)
        if name_only.returncode != 0:
            repos[repo_name] = {"branch": spec.branch, "base": spec.base, "error": name_only.stderr.strip()}
            continue
        files = [line for line in name_only.stdout.splitlines() if line]
        modules = sorted({f.split("/")[0] for f in files if f})
        entry = {"branch": spec.branch, "base": spec.base, "files": files, "modules": modules}
        if mode == "patch":
            entry["diff"] = git_run(["diff", rng], cwd=wt, check=False).stdout
        elif mode == "stat":
            entry["stat"] = git_run(["diff", "--stat", rng], cwd=wt, check=False).stdout
        repos[repo_name] = entry
    return {"instance": instance, "repos": repos}


def _point_latest(directory: str, link_name: str, target_name: str) -> None:
    """(Re)point a `latest`-style symlink at target_name within the same directory.

    Relative target so the dumps dir stays relocatable; replaces any existing
    link (including a broken one) atomically enough for single-user tooling.
    """
    link = os.path.join(directory, link_name)
    if os.path.lexists(link):
        os.unlink(link)
    os.symlink(target_name, link)


def run_instance_script(instance: str, workspace_root: str, script: str) -> dict:
    """Execute a script for an instance, persist its NDJSON, and tally results.

    Each run is written to an immutable, timestamped record
    ``_dumps/<instance>/<script>-<ts>.ndjson``; two symlinks are then repointed
    at it — ``<script>-latest.ndjson`` (newest run of this script) and
    ``latest.ndjson`` (newest run of any script, what `compare_instance` reads
    when no explicit script is named). The returned ``ndjson_path`` is the
    timestamped file, so a later `owm_get_script_failures(ndjson_path)` still
    resolves to this exact run rather than whatever ran most recently.

    Returns {status, summary, failures, ndjson_path} on completion, or
    {status: "abort", reason, rows_run, ndjson_path} when the script signals abort.
    """
    ndjson_dir = os.path.join(workspace_root, "_dumps", instance)
    os.makedirs(ndjson_dir, exist_ok=True)

    stdout = execute_script(instance, script, workspace_root)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S")
    stem = f"{script}-{ts}"
    ndjson_name = f"{stem}.ndjson"
    n = 2
    while os.path.exists(os.path.join(ndjson_dir, ndjson_name)):  # >1 run in the same second
        ndjson_name = f"{stem}-{n}.ndjson"
        n += 1
    ndjson_path = os.path.join(ndjson_dir, ndjson_name)
    with open(ndjson_path, "w") as f:
        f.write(stdout)
    _point_latest(ndjson_dir, f"{script}-latest.ndjson", ndjson_name)
    _point_latest(ndjson_dir, "latest.ndjson", ndjson_name)

    result = run_script(instance, script, ndjson_output=stdout)

    if result.status == "abort":
        return {
            "status": "abort",
            "reason": result.abort_reason,
            "rows_run": result.rows_run,
            "ndjson_path": ndjson_path,
        }

    failures = [r for r in result.rows if r.get("status") == "FAIL" and not r.get("_non_conforming")]
    return {
        "status": result.status,
        "summary": {
            "ok": result.summary.ok,
            "fail": result.summary.fail,
            "warn": result.summary.warn,
            "none": result.summary.none,
            "total": result.summary.total,
        },
        "failures": failures,
        "ndjson_path": ndjson_path,
    }


def compare_instance(instance: str, workspace_root: str, base: str | None = None,
                     script: str | None = None) -> dict:
    """Diff one instance's script run against another instance's.

    The comparison is symmetric — `base` is just the other instance to diff
    against (feature-vs-base is the common case, not a requirement), and it
    defaults to the partner named in workspace.toml's compare_pairs. `script`
    selects which run to diff: when given, follows each instance's
    ``<script>-latest.ndjson`` symlink to that script's newest run; when omitted,
    follows ``latest.ndjson`` (each instance's most recent run of any script).
    Both symlinks are maintained by `run_instance_script`. Returns
    {status, base, feat, unexpected, summary}, or an ErrorResponse dict when no
    compare target is configured or an instance's NDJSON is missing.
    """
    with open(os.path.join(workspace_root, "workspace.toml")) as f:
        ws = parse_workspace_config(f.read())

    base_instance = base
    if not base_instance:
        for pair in ws.compare_pairs:
            if instance in pair:
                base_instance = next(p for p in pair if p != instance)
                break

    if not base_instance:
        return format_error("no compare target configured", NO_COMPARE_TARGET,
                            hint="add compare_pairs to workspace.toml or pass --base")

    ndjson_name = f"{script}-latest.ndjson" if script else "latest.ndjson"

    def _read_ndjson(inst):
        path = os.path.join(workspace_root, "_dumps", inst, ndjson_name)
        if not os.path.exists(path):
            return None
        with open(path) as fh:
            return [json.loads(line) for line in fh if line.strip()]

    result = compare_instances(
        instance=instance,
        base=base_instance,
        workspace_root=workspace_root,
        workspace_compare_pairs=ws.compare_pairs,
        base_rows=_read_ndjson(base_instance),
        feat_rows=_read_ndjson(instance),
    )

    if result.status == "error":
        return format_error(result.error or "compare failed", NOT_FOUND,
                            instance=result.missing_instance)

    out = {
        "status": result.status,
        "base": result.base_instance,
        "feat": result.feat_instance,
        "unexpected": result.unexpected,
        "summary": {},
    }
    if result.summary:
        out["summary"] = {
            "total": result.summary.total,
            "unexpected_changes": result.summary.unexpected_changes,
        }
    return out
