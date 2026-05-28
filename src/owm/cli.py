import os
import sys
from pathlib import Path

import click

from owm.api import instance_status, workspace_status
from owm.config import parse_instance_config, parse_workspace_config
from owm.errors import OwmError
from owm.instance import (
    new_instance, create_instance, list_running_instances,
    start_instance, stop_instance, kill_instance, health_check,
    _read_pid, _process_alive,
)
from owm.archive import archive_instance
from owm.env import resolve_env, format_env
from owm.modules import upgrade_modules
from owm.operations import (
    infer_instance_from_cwd,
    delete_instance, rename_instance, show_logs,
    db_dump, db_restore, validate_instance,
)
from owm.sync import (
    fetch_workspace, sync_instance, push_instance, reset_instance,
    git_fetch_bare, read_repo_state, git_fast_forward, git_rebase,
    git_push, git_reset_hard,
)
from owm.worktrees import resolve_worktree_path


def _find_workspace_root(start: Path | None = None) -> str:
    current = start or Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / "workspace.toml").exists():
            return str(parent)
    raise click.UsageError(
        "No workspace.toml found. Run from inside a workspace or pass --workspace."
    )


def _resolve_workspace(ctx) -> str:
    w = ctx.obj.get("workspace")
    if w:
        return w
    env = os.environ.get("OWM_WORKSPACE")
    if env:
        return env
    return _find_workspace_root()


def _resolve_instance(ctx, name: str | None) -> str:
    """Return name if given; otherwise infer from CWD position inside instances/."""
    workspace_root = _resolve_workspace(ctx)
    if name:
        return name
    result = infer_instance_from_cwd(
        cwd=str(Path.cwd()),
        workspace_root=workspace_root,
        instances_dir="instances",
    )
    if not result.instance:
        raise click.UsageError(
            "No instance name given and CWD is not inside an instance directory.\n"
            "Specify a name (e.g. owm start feat-789) or cd into an instance folder."
        )
    return result.instance


def _is_running(instance: str, workspace_root: str) -> bool:
    pid = _read_pid(instance, workspace_root)
    return pid is not None and _process_alive(pid)


def _read_instance_conf(instance: str, workspace_root: str):
    path = os.path.join(workspace_root, "instances", instance, "instance.toml")
    with open(path) as f:
        return parse_instance_config(f.read())


def _workspace_compare_pairs(workspace_root: str) -> list:
    toml_path = os.path.join(workspace_root, "workspace.toml")
    with open(toml_path) as f:
        return parse_workspace_config(f.read()).compare_pairs


@click.group()
@click.option(
    "--workspace", "-w",
    default=None,
    metavar="PATH",
    help="Workspace root (default: walk up from CWD for workspace.toml).",
)
@click.pass_context
def cli(ctx, workspace):
    ctx.ensure_object(dict)
    ctx.obj["workspace"] = workspace


def _parse_repo_specs(repos: tuple) -> dict[str, str]:
    repo_dict: dict[str, str] = {}
    for r in repos:
        if "=" not in r:
            raise click.UsageError(
                f"Invalid repo spec {r!r}; expected name=branch:base (e.g. odoo=main:shared)"
            )
        k, v = r.split("=", 1)
        repo_dict[k] = v
    return repo_dict


@cli.command("create")
@click.argument("name", required=False)
@click.argument("repos", nargs=-1, metavar="name=branch:base ...")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing instance.toml if REPOS given.")
@click.option("--toml-only", is_flag=True, help="Write instance.toml and stop — do not materialise.")
@click.pass_context
def cmd_create(ctx, name, repos, force, toml_only):
    """Create and materialise an instance.

    With REPOS: writes instance.toml then materialises (one-shot).
    Without REPOS: materialises from an existing instance.toml.
    With --toml-only: writes instance.toml and stops, so you can review
    before running again to materialise.

    Examples:

      owm create feat-789 odoo=main:shared product-core=feat-789-dev:main

      owm create feat-789 odoo=main:shared --toml-only   # review, then run again

      owm create feat-789          # materialise from existing toml
    """
    if repos and not name:
        raise click.UsageError("NAME is required when REPOS are specified.")
    if toml_only and not repos:
        raise click.UsageError("--toml-only requires REPOS to be specified.")
    instance = _resolve_instance(ctx, name)
    workspace_root = _resolve_workspace(ctx)

    if repos:
        repo_dict = _parse_repo_specs(repos)
        try:
            new_result = new_instance(name=instance, repos=repo_dict, workspace_root=workspace_root, force=force)
        except OwmError as e:
            click.echo(f"error: {e.args[0]} [{e.code}]", err=True)
            sys.exit(1)
        if toml_only:
            click.echo(new_result.toml_path)
            return

    try:
        result = create_instance(instance, workspace_root)
    except OwmError as e:
        click.echo(f"error: {e.args[0]} [{e.code}]", err=True)
        sys.exit(1)
    if result.status == "up_to_date":
        click.echo(f"{instance}  up to date")
    elif result.status == "created":
        click.echo(f"{instance}  created  https://{instance}.localhost")
    else:
        click.echo(f"{instance}  {result.status}")


@cli.command("list")
@click.pass_context
def cmd_list(ctx):
    """List running instances in the workspace."""
    workspace_root = _resolve_workspace(ctx)
    instances = list_running_instances(workspace_root)
    if not instances:
        click.echo("no running instances")
        return
    for inst in instances:
        url = inst.get("url") or ""
        line = f"{inst['instance']}  pid={inst['pid']}  port={inst['port']}  {inst['status']}"
        if url:
            line += f"  {url}"
        click.echo(line)


@cli.command("start")
@click.argument("name", required=False)
@click.option("--wait/--no-wait", default=False, help="Block until HTTP responds.")
@click.pass_context
def cmd_start(ctx, name, wait):
    """Start an instance. NAME may be omitted when inside an instance directory."""
    instance = _resolve_instance(ctx, name)
    workspace_root = _resolve_workspace(ctx)
    try:
        result = start_instance(instance, workspace_root, wait=wait)
    except OwmError as e:
        click.echo(f"error: {e.args[0]} [{e.code}]", err=True)
        sys.exit(1)
    if result.status == "already_running":
        click.echo(f"{instance} already running (pid {result.pid})")
    elif result.status == "healthy":
        click.echo(f"{instance} started  pid={result.pid}  {result.url or ''}")
    else:
        click.echo(f"{instance} spawned  pid={result.pid}")


@cli.command("stop")
@click.argument("name", required=False)
@click.option("--wait/--no-wait", default=True, help="Block until process exits.")
@click.pass_context
def cmd_stop(ctx, name, wait):
    """Stop an instance. NAME may be omitted when inside an instance directory."""
    instance = _resolve_instance(ctx, name)
    workspace_root = _resolve_workspace(ctx)
    try:
        result = stop_instance(instance, workspace_root, wait=wait)
    except OwmError as e:
        click.echo(f"error: {e.args[0]} [{e.code}]", err=True)
        sys.exit(1)
    if result.status == "not_running":
        click.echo(f"{instance} is not running")
    elif result.status == "stopped":
        click.echo(f"{instance} stopped")
    elif result.status == "stop_timeout":
        click.echo(f"warning: {instance} did not stop in time — {result.hint}", err=True)
        sys.exit(1)
    else:
        click.echo(f"{instance} stopping (pid {result.pid})")


@cli.command("kill")
@click.argument("name", required=False)
@click.pass_context
def cmd_kill(ctx, name):
    """Force-kill an instance process. NAME may be omitted when inside an instance directory."""
    instance = _resolve_instance(ctx, name)
    workspace_root = _resolve_workspace(ctx)
    result = kill_instance(instance, workspace_root)
    if result.status == "not_running":
        click.echo(f"{instance}  not running")
    else:
        click.echo(f"{instance}  killed  pid={result.pid}")


@cli.command("health")
@click.argument("name", required=False)
@click.pass_context
def cmd_health(ctx, name):
    """Check instance health (HTTP, DB, process). NAME may be omitted when inside an instance directory."""
    instance = _resolve_instance(ctx, name)
    workspace_root = _resolve_workspace(ctx)
    h = health_check(instance, workspace_root)
    line = f"{instance}  {h.get('status', 'unknown')}"
    if h.get("pid"):
        line += f"  pid={h['pid']}"
    if h.get("url"):
        line += f"  {h['url']}"
    click.echo(line)


@cli.command("status")
@click.argument("name", required=False)
@click.pass_context
def cmd_status(ctx, name):
    """Show status. With NAME or from inside an instance dir: instance detail.
    From the workspace root: workspace summary."""
    workspace_root = _resolve_workspace(ctx)

    # Try to resolve instance — fall back to workspace summary if none found
    instance = name
    if not instance:
        result = infer_instance_from_cwd(
            cwd=str(Path.cwd()),
            workspace_root=workspace_root,
            instances_dir="instances",
        )
        instance = result.instance

    if instance:
        r = instance_status(instance, workspace_root)
        if "error" in r:
            raise click.ClickException(r["error"])
        line = f"{instance}  {r['state']}"
        if r.get("pid"):
            line += f"  pid={r['pid']}"
        line += f"  {r['url'] or r['local_url']}"
        if r.get("suspected_linked"):
            sl = r["suspected_linked"]
            line += f"\n  ! {sl['classification']}  pid={sl['pid']}  {sl.get('name', '')}"
        click.echo(line)
    else:
        r = workspace_status(workspace_root)
        if not r["instances"]:
            click.echo("no instances configured")
            return
        for inst, info in sorted(r["instances"].items()):
            line = f"{inst}  {info['state']}"
            if info.get("pid"):
                line += f"  pid={info['pid']}"
            if info.get("url"):
                line += f"  {info['url']}"
            click.echo(line)
        for w in r.get("workspace_warnings", []):
            click.echo(f"  warning: {w['type']}  {w.get('path', '')}", err=True)
        for a in r.get("port_alerts", []):
            click.echo(f"  alert: port conflict on {a['instance']}:{a['http_port']}  ({a['classification']})", err=True)


@cli.command("delete")
@click.argument("name", required=False)
@click.option("--force", "-f", is_flag=True, help="Skip confirmation checklist and delete immediately.")
@click.pass_context
def cmd_delete(ctx, name, force):
    """Delete an instance and all its resources."""
    instance = _resolve_instance(ctx, name)
    workspace_root = _resolve_workspace(ctx)
    running = _is_running(instance, workspace_root)
    compare_pairs = _workspace_compare_pairs(workspace_root)
    try:
        result = delete_instance(
            instance=instance,
            running=running,
            force=force,
            workspace_root=workspace_root,
            workspace_compare_pairs=compare_pairs,
        )
    except OwmError as e:
        click.echo(f"error: {e.args[0]} [{e.code}]", err=True)
        sys.exit(1)
    if result.status == "pending_confirmation":
        click.echo(f"instance {instance!r} — pass --force to confirm deletion:", err=True)
        for item in result.checklist or []:
            click.echo(f"  • {item}", err=True)
        sys.exit(1)
    click.echo(f"{instance}  deleted")


@cli.command("rename")
@click.argument("name")
@click.argument("new_name")
@click.pass_context
def cmd_rename(ctx, name, new_name):
    """Rename an instance. Requires the instance to be stopped."""
    workspace_root = _resolve_workspace(ctx)
    cwd_inst = infer_instance_from_cwd(
        cwd=str(Path.cwd()), workspace_root=workspace_root, instances_dir="instances",
    )
    if cwd_inst.instance == name:
        raise click.UsageError(
            f"You are inside {name!r} — cd to the workspace root before renaming."
        )
    running = _is_running(name, workspace_root)
    compare_pairs = _workspace_compare_pairs(workspace_root)
    try:
        result = rename_instance(
            instance=name,
            new_name=new_name,
            running=running,
            workspace_compare_pairs=compare_pairs,
        )
    except OwmError as e:
        click.echo(f"error: {e.args[0]} [{e.code}]", err=True)
        sys.exit(1)
    click.echo(f"{name} → {new_name}")
    if result.old_url and result.new_url:
        click.echo(f"  {result.old_url} → {result.new_url}")


@cli.command("logs")
@click.argument("name", required=False)
@click.option("--lines", "-n", default=50, show_default=True, help="Number of lines to show.")
@click.option("--level", default=None, help="Filter by log level (e.g. ERROR).")
@click.option("--follow", "-f", is_flag=True, help="Stream new log lines (not yet implemented).")
@click.pass_context
def cmd_logs(ctx, name, lines, level, follow):
    """Show recent log lines for an instance."""
    if follow:
        raise NotImplementedError("--follow is not yet implemented")
    instance = _resolve_instance(ctx, name)
    workspace_root = _resolve_workspace(ctx)
    try:
        result = show_logs(instance=instance, n=lines, follow=False, level=level,
                           workspace_root=workspace_root)
    except OwmError as e:
        click.echo(f"error: {e.args[0]} [{e.code}]", err=True)
        sys.exit(1)
    if result.warning:
        click.echo(f"warning: {result.warning}", err=True)
    for line in result.lines:
        if isinstance(line, dict):
            ts = line.get("ts") or line.get("time") or ""
            lvl = line.get("level") or line.get("severity") or ""
            msg = line.get("msg") or line.get("message") or str(line)
            parts = [p for p in (ts, lvl, msg) if p]
            click.echo("  ".join(parts))
        else:
            click.echo(str(line))


@cli.command("db-dump")
@click.argument("name", required=False)
@click.option("--out", default=None, metavar="PATH", help="Output path (default: _dumps/<instance>/<ts>.dump).")
@click.pass_context
def cmd_db_dump(ctx, name, out):
    """Dump an instance database to a file."""
    instance = _resolve_instance(ctx, name)
    workspace_root = _resolve_workspace(ctx)
    conf = _read_instance_conf(instance, workspace_root)
    try:
        result = db_dump(
            instance=instance,
            out=out,
            workspace_root=workspace_root,
            db_name=conf.database.name,
            pg_port=conf.database.pg_port,
        )
    except OwmError as e:
        click.echo(f"error: {e.args[0]} [{e.code}]", err=True)
        sys.exit(1)
    click.echo(f"dump: {result.path}")


@cli.command("db-restore")
@click.argument("name", required=False)
@click.argument("path_arg", metavar="PATH")
@click.pass_context
def cmd_db_restore(ctx, name, path_arg):
    """Restore an instance database from a dump file. Requires the instance to be stopped."""
    instance = _resolve_instance(ctx, name)
    workspace_root = _resolve_workspace(ctx)
    conf = _read_instance_conf(instance, workspace_root)
    running = _is_running(instance, workspace_root)
    try:
        result = db_restore(
            instance=instance,
            path=path_arg,
            workspace_root=workspace_root,
            db_name=conf.database.name,
            pg_port=conf.database.pg_port,
            running=running,
        )
    except OwmError as e:
        click.echo(f"error: {e.args[0]} [{e.code}]", err=True)
        sys.exit(1)
    click.echo(f"restored: {result.resolved_path}")


@cli.command("env")
@click.argument("name", required=False)
@click.option("--format", "fmt", default=None,
              type=click.Choice(["dotenv", "json", "shell"]),
              help="Output format (default: human-readable table).")
@click.pass_context
def cmd_env(ctx, name, fmt):
    """Print environment variables for an instance."""
    instance = _resolve_instance(ctx, name)
    workspace_root = _resolve_workspace(ctx)
    conf = _read_instance_conf(instance, workspace_root)
    env = resolve_env(
        instance=instance,
        workspace_root=workspace_root,
        instance_http_port=conf.server.http_port,
        instance_gevent_port=conf.server.gevent_port,
    )
    click.echo(format_env(env, fmt))


@cli.command("archive")
@click.argument("name", required=False)
@click.option("--discard-db", is_flag=True, help="Drop the database instead of dumping it.")
@click.pass_context
def cmd_archive(ctx, name, discard_db):
    """Archive an instance. Requires the instance to be stopped."""
    instance = _resolve_instance(ctx, name)
    workspace_root = _resolve_workspace(ctx)
    running = _is_running(instance, workspace_root)
    try:
        archive_instance(instance=instance, workspace_root=workspace_root,
                         running=running, discard_db=discard_db)
    except OwmError as e:
        click.echo(f"error: {e.args[0]} [{e.code}]", err=True)
        sys.exit(1)
    click.echo(f"{instance}  archived  _archive/{instance}/")


@cli.command("upgrade")
@click.argument("name")
@click.argument("modules", nargs=-1)
@click.option("--reinstall", is_flag=True, help="Re-install modules rather than upgrade.")
@click.pass_context
def cmd_upgrade(ctx, name, modules, reinstall):
    """Upgrade (or reinstall) modules for an instance.

    With no MODULES: upgrades all. With MODULES: upgrades only the listed ones.
    """
    workspace_root = _resolve_workspace(ctx)
    modules_list = list(modules) if modules else None
    result = upgrade_modules(instance=name, modules=modules_list, reinstall=reinstall)
    label = "reinstalled" if reinstall else "upgraded"
    mods = result.modules if isinstance(result.modules, list) else result.modules
    click.echo(f"{name}  {label}  {mods}")


@cli.command("validate")
@click.argument("name", required=False)
@click.option("--live", is_flag=True, help="Also check worktrees, DB, venv, and proxy block.")
@click.pass_context
def cmd_validate(ctx, name, live):
    """Validate instance configuration. Static by default; --live checks materialised state."""
    instance = _resolve_instance(ctx, name)
    workspace_root = _resolve_workspace(ctx)
    toml_path = os.path.join(workspace_root, "instances", instance, "instance.toml")
    toml_valid = True
    missing_fields = []
    try:
        with open(toml_path) as f:
            parse_instance_config(f.read())
    except FileNotFoundError:
        toml_valid = False
        missing_fields = ["instance.toml not found — run owm create --toml-only first"]
    except Exception as e:
        toml_valid = False
        missing_fields = [str(e)]
    result = validate_instance(
        instance=instance,
        live=live,
        toml_valid=toml_valid,
        missing_fields=missing_fields if not toml_valid else None,
    )
    if result.valid:
        suffix = "  (live)" if result.live_checks_run else ""
        click.echo(f"{instance}  ok{suffix}")
    else:
        for err in result.errors:
            click.echo(f"error: {err}", err=True)
        sys.exit(1)


def _gather_repo_states(instance: str, workspace_root: str) -> dict:
    conf = _read_instance_conf(instance, workspace_root)
    states = {}
    for name, rspec in conf.repos.items():
        wt = resolve_worktree_path(
            repo=name, branch=rspec.branch, shared=rspec.shared,
            workspace_root=workspace_root, instance_name=instance,
        )
        state = read_repo_state(wt.path) if os.path.isdir(wt.path) else {"status": "clean"}
        state["shared"] = rspec.shared
        states[name] = state
    return states


# ---------------------------------------------------------------------------
# owm fetch
# ---------------------------------------------------------------------------

@cli.command("fetch")
@click.pass_context
def cmd_fetch(ctx):
    """Fetch all bare repos in the workspace."""
    workspace_root = _resolve_workspace(ctx)
    toml_path = os.path.join(workspace_root, "workspace.toml")
    with open(toml_path) as f:
        ws_conf = parse_workspace_config(f.read())
    repos = list(ws_conf.repos.keys())
    repos_with_updates = []
    unreachable = []
    for name in repos:
        bare_path = os.path.join(workspace_root, "_repos", f"{name}.git")
        if not os.path.isdir(bare_path):
            continue
        click.echo(f"  fetching {name}...", nl=False)
        try:
            updated = git_fetch_bare(bare_path)
        except OwmError as e:
            click.echo(f"  warning: {e.args[0]} [{e.code}]")
            unreachable.append(name)
            continue
        click.echo("  updated" if updated else "  up to date")
        if updated:
            repos_with_updates.append(name)
    result = fetch_workspace(
        repos=repos, repos_with_updates=repos_with_updates,
        unreachable_repos=unreachable,
    )
    if not repos:
        click.echo("no repos configured")


# ---------------------------------------------------------------------------
# owm sync
# ---------------------------------------------------------------------------

@cli.command("sync")
@click.argument("name", required=False)
@click.option("--repo", default=None, help="Sync only this repo.")
@click.option("--rebase", is_flag=True, help="Rebase instead of fast-forward.")
@click.pass_context
def cmd_sync(ctx, name, repo, rebase):
    """Sync an instance's worktrees with their upstream base branches."""
    instance = _resolve_instance(ctx, name)
    workspace_root = _resolve_workspace(ctx)
    repo_states = _gather_repo_states(instance, workspace_root)
    results = sync_instance(instance, repo_states, rebase=rebase, repo=repo)
    conf = _read_instance_conf(instance, workspace_root)
    for rname, outcome in results.items():
        status = outcome["status"]
        if status == "fast-forwarded":
            rspec = conf.repos[rname]
            wt = resolve_worktree_path(
                repo=rname, branch=rspec.branch, shared=rspec.shared,
                workspace_root=workspace_root, instance_name=instance,
            )
            git_fast_forward(wt.path)
        elif status == "rebased":
            rspec = conf.repos[rname]
            wt = resolve_worktree_path(
                repo=rname, branch=rspec.branch, shared=rspec.shared,
                workspace_root=workspace_root, instance_name=instance,
            )
            git_rebase(wt.path)
        click.echo(f"  {rname}  {status}")


# ---------------------------------------------------------------------------
# owm push
# ---------------------------------------------------------------------------

@cli.command("push")
@click.argument("name", required=False)
@click.option("--repo", default=None, help="Push only this repo.")
@click.option("--all", "all_repos", is_flag=True, help="Push all owned repos.")
@click.pass_context
def cmd_push(ctx, name, repo, all_repos):
    """Push instance branches to origin."""
    instance = _resolve_instance(ctx, name)
    workspace_root = _resolve_workspace(ctx)
    repo_states = _gather_repo_states(instance, workspace_root)
    try:
        results = push_instance(
            instance, repo=repo, all_repos=all_repos, repo_states=repo_states,
        )
    except OwmError as e:
        click.echo(f"error: {e.args[0]} [{e.code}]", err=True)
        sys.exit(1)
    conf = _read_instance_conf(instance, workspace_root)
    for rname, outcome in results.items():
        if outcome["status"] == "pushed":
            rspec = conf.repos[rname]
            wt = resolve_worktree_path(
                repo=rname, branch=rspec.branch, shared=rspec.shared,
                workspace_root=workspace_root, instance_name=instance,
            )
            git_push(wt.path)
        click.echo(f"  {rname}  {outcome['status']}")


# ---------------------------------------------------------------------------
# owm reset
# ---------------------------------------------------------------------------

@cli.command("reset")
@click.argument("name", required=False)
@click.option("--repo", default=None, help="Reset only this repo.")
@click.option("--force", is_flag=True, help="Discard uncommitted changes.")
@click.option("--all", "all_repos", is_flag=True, help="Reset all non-shared repos.")
@click.pass_context
def cmd_reset(ctx, name, repo, force, all_repos):
    """Reset instance worktrees to origin HEAD."""
    instance = _resolve_instance(ctx, name)
    workspace_root = _resolve_workspace(ctx)
    repo_states = _gather_repo_states(instance, workspace_root)
    try:
        results = reset_instance(
            instance, repo=repo, force=force, all_repos=all_repos, repo_states=repo_states,
        )
    except OwmError as e:
        click.echo(f"error: {e.args[0]} [{e.code}]", err=True)
        sys.exit(1)
    conf = _read_instance_conf(instance, workspace_root)
    for rname, outcome in results.items():
        if outcome["status"] == "reset":
            rspec = conf.repos[rname]
            wt = resolve_worktree_path(
                repo=rname, branch=rspec.branch, shared=rspec.shared,
                workspace_root=workspace_root, instance_name=instance,
            )
            git_reset_hard(wt.path)
        click.echo(f"  {rname}  {outcome['status']}")
