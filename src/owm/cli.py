import json
import os
import subprocess
import sys
import webbrowser
from pathlib import Path

import click

from owm.api import instance_status, workspace_status
from owm.config import parse_instance_config, parse_workspace_config
from owm.addons import resolve_addons_path
from owm.database import check_pg_reachability
from owm.errors import OwmError
from owm.instance import (
    new_instance, create_instance, list_running_instances,
    start_instance, stop_instance, kill_instance, health_check,
    generate_instance_conf, find_odoo_repo,
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
from owm.database import reset_db
from owm.oplog import workspace_log
from owm.sync import (
    fetch_workspace, sync_instance, push_instance, reset_instance,
    git_fetch_bare, read_repo_state, git_fast_forward, git_rebase,
    git_push, git_reset_hard,
)
from owm.workspace import init_workspace
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


@cli.command("init")
@click.option(
    "--local-copies", default=None, metavar="PATH",
    help="Workspace dir to scan for existing bare repos; clones from local instead of downloading.",
)
@click.pass_context
def cmd_init(ctx, local_copies):
    """Initialise a workspace from workspace.toml in the current directory.

    Creates the directory structure, bare-clones all repos declared in [repos],
    provisions Postgres clusters declared in [clusters] (idempotent — skips if
    already running), and writes a proxy config stub to _proxy/.

    Safe to re-run: existing repos, running clusters, and existing roles are skipped.

    \b
    Examples:
      owm init
      owm init --local-copies ~/old-workspace   # clone objects from local copy
    """
    workspace_root = str(Path.cwd())
    toml_path = os.path.join(workspace_root, "workspace.toml")
    if not os.path.isfile(toml_path):
        click.echo("error: no workspace.toml in current directory", err=True)
        sys.exit(1)
    click.echo("initialising workspace…")
    try:
        result = init_workspace(workspace_root, local_copies_dir=local_copies)
    except Exception as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)
    for clone in sorted(result.clones, key=lambda c: c.name):
        if clone.status == "error":
            click.echo(f"  error: {clone.name}: {clone.error}", err=True)
        elif clone.status == "skipped":
            click.echo(f"  {clone.name}  (already exists)")
        elif clone.status == "local_copy":
            click.echo(f"  {clone.name}  cloned from local copy")
        else:
            click.echo(f"  {clone.name}  cloned")
    pg = result.postgres
    if pg.clusters_created:
        click.echo(f"  pg: created {', '.join(pg.clusters_created)}")
    if pg.clusters_started:
        click.echo(f"  pg: started {', '.join(pg.clusters_started)}")
    if pg.superuser_created:
        click.echo(f"  pg: created superuser role {pg.superuser_role!r}")
    if pg.skipped:
        click.echo("  pg: clusters already running")
    if result.proxy_stub_path:
        click.echo(f"  proxy stub: {result.proxy_stub_path}")
    click.echo("done.")


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
        if e.code == "PORT_CONTESTED" and "port" in e.extra:
            click.echo(f"  hint: lsof -i :{e.extra['port']}", err=True)
        sys.exit(1)
    if result.status == "already_running":
        click.echo(f"{instance} already running (pid {result.pid})")
    elif result.status == "healthy":
        click.echo(f"{instance} started  pid={result.pid}  {result.url or ''}")
    else:
        click.echo(f"{instance} spawned  pid={result.pid}")


@cli.command("install")
@click.argument("name", required=False)
@click.argument("modules", nargs=-1, required=False)
@click.option("--timeout", default=600, show_default=True, metavar="SECS", help="Seconds to wait for Odoo to finish installing.")
@click.option("--no-save", is_flag=True, help="Do not append modules to instance.toml.")
@click.pass_context
def cmd_install(ctx, name, modules, timeout, no_save):
    """Install Odoo modules into an instance database, then stop.

    With MODULES: installs them and appends to [install].modules in instance.toml.
    Without MODULES: installs from [install].modules already declared in instance.toml.
    Use --no-save to install without updating the toml.

    Uses Odoo -i (install). For modules already installed, use `owm upgrade` (-u).

    \b
    Examples:
      owm install feat-789 sale purchase   # install + save to toml
      owm install feat-789                 # install from toml manifest
      owm install feat-789 sale --no-save  # install without saving
    """
    from owm.instance import _append_modules_to_toml, _query_installed_modules
    instance = _resolve_instance(ctx, name)
    workspace_root = _resolve_workspace(ctx)
    toml_path = os.path.join(workspace_root, "instances", instance, "instance.toml")

    try:
        with open(toml_path) as f:
            conf = parse_instance_config(f.read())
    except Exception as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)

    if modules:
        install_modules = list(modules)
    else:
        install_modules = conf.install.modules if conf.install else []
        if not install_modules:
            click.echo("error: no modules specified and none declared in [install].modules", err=True)
            sys.exit(1)

    if _is_running(instance, workspace_root):
        click.echo("error: stop the instance first", err=True)
        sys.exit(1)

    already_in_db = _query_installed_modules(conf.database.name, conf.database.pg_port, install_modules)
    to_install = [m for m in install_modules if m not in already_in_db]

    if already_in_db:
        click.echo(f"  note: {', '.join(already_in_db)} already installed in DB — use `owm upgrade` to update")

    if to_install:
        click.echo(f"installing {','.join(to_install)} into {instance} …")
        try:
            start_instance(
                instance, workspace_root,
                wait=True,
                timeout_seconds=timeout,
                init_modules=to_install,
            )
        except OwmError as e:
            click.echo(f"error: {e.args[0]} [{e.code}]", err=True)
            sys.exit(1)
        stop_instance(instance, workspace_root, wait=True)
    else:
        click.echo(f"  nothing to install")

    if modules and not no_save:
        added, _ = _append_modules_to_toml(toml_path, install_modules)
        if added:
            click.echo(f"  manifest: added {', '.join(added)}")
    click.echo(f"{instance}  install complete")


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


@cli.command("restart")
@click.argument("name", required=False)
@click.pass_context
def cmd_restart(ctx, name):
    """Stop then start an instance."""
    instance = _resolve_instance(ctx, name)
    workspace_root = _resolve_workspace(ctx)
    try:
        stop_instance(instance, workspace_root, wait=True)
        result = start_instance(instance, workspace_root, wait=False)
    except OwmError as e:
        click.echo(f"error: {e.args[0]} [{e.code}]", err=True)
        sys.exit(1)
    click.echo(f"{instance}  restarted  pid={result.pid}")


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


@cli.command("open")
@click.argument("name", required=False)
@click.pass_context
def cmd_open(ctx, name):
    """Open the instance URL in the default browser."""
    instance = _resolve_instance(ctx, name)
    workspace_root = _resolve_workspace(ctx)
    ws_toml_path = os.path.join(workspace_root, "workspace.toml")
    with open(ws_toml_path) as f:
        ws_conf = parse_workspace_config(f.read())
    domain = ws_conf.proxy.domain_suffix if ws_conf.proxy else "localhost"
    url = f"https://{instance}.{domain}"
    webbrowser.open(url)
    click.echo(url)


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
@click.option("--force", "-f", is_flag=True, help="Skip interactive confirmation (for scripting).")
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
        for item in result.checklist or []:
            click.echo(f"  • {item}")
        click.echo("  pass --force to skip this prompt")
        if not click.confirm(f"Delete {instance!r}?", default=False):
            click.echo("aborted")
            sys.exit(1)
        try:
            result = delete_instance(
                instance=instance,
                running=running,
                force=True,
                workspace_root=workspace_root,
                workspace_compare_pairs=compare_pairs,
            )
        except OwmError as e:
            click.echo(f"error: {e.args[0]} [{e.code}]", err=True)
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
            workspace_root=workspace_root,
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
@click.option("--follow", "-f", is_flag=True, help="Stream new log lines (tail -f).")
@click.pass_context
def cmd_logs(ctx, name, lines, level, follow):
    """Show recent log lines for an instance."""
    instance = _resolve_instance(ctx, name)
    workspace_root = _resolve_workspace(ctx)
    if follow:
        instance_dir = os.path.join(workspace_root, "instances", instance)
        if not os.path.isdir(instance_dir):
            click.echo(f"error: instance {instance!r} not found", err=True)
            sys.exit(1)
        log_path = os.path.join(instance_dir, "instance.log")
        if level:
            click.echo("warning: --level is ignored with --follow", err=True)
        os.execvp("tail", ["tail", "-f", log_path])
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
            if "raw" in line and len(line) == 1:
                click.echo(line["raw"])
                continue
            ts = line.get("ts") or line.get("time") or ""
            lvl = line.get("level") or line.get("severity") or ""
            msg = line.get("msg") or line.get("message") or str(line)
            parts = [p for p in (ts, lvl, msg) if p]
            click.echo("  ".join(parts))
        else:
            click.echo(str(line))


@cli.command("shell")
@click.argument("name", required=False)
@click.option("--script", metavar="FILE", default=None, help="Script to pipe through odoo-bin shell (use - for stdin).")
@click.option("--json", "json_out", is_flag=True, help="Output result as JSON (non-interactive only).")
@click.pass_context
def cmd_shell(ctx, name, script, json_out):
    """Open an interactive Odoo shell, or pipe a script through it non-interactively."""
    instance = _resolve_instance(ctx, name)
    workspace_root = _resolve_workspace(ctx)
    if _is_running(instance, workspace_root):
        click.echo("error: stop the instance first", err=True)
        sys.exit(1)
    conf = _read_instance_conf(instance, workspace_root)
    odoo_repo_name, odoo_spec = find_odoo_repo(conf)
    wt = resolve_worktree_path(odoo_repo_name, odoo_spec.branch, True, workspace_root, instance)
    odoo_bin = os.path.join(wt.path, "odoo-bin")
    venv = os.path.join(workspace_root, "instances", instance, ".venv")
    python = os.path.join(venv, "bin", "python")
    conf_path = os.path.join(workspace_root, "instances", instance, "instance.conf")

    for label, path in [("instance.conf", conf_path), ("odoo-bin", odoo_bin), ("venv", venv)]:
        if not os.path.exists(path):
            click.echo(f"error: {label} not found at {path} — run owm create first", err=True)
            sys.exit(1)

    cmd = [python, odoo_bin, "shell", "-c", conf_path, "-d", conf.database.name, "--no-http"]

    if not script:
        os.execv(python, cmd)

    # Non-interactive
    if script == "-":
        script_input = sys.stdin.read()
    else:
        with open(script) as f:
            script_input = f.read()

    result = subprocess.run(
        cmd + ["--log-level", "critical"],
        input=script_input, capture_output=True, text=True,
    )
    if json_out:
        click.echo(json.dumps({"exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}))
    else:
        if result.stdout:
            click.echo(result.stdout, nl=False)
        if result.stderr:
            click.echo(result.stderr, nl=False, err=True)
        sys.exit(result.returncode)


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


@cli.command("db-reset")
@click.argument("name", required=False)
@click.pass_context
def cmd_db_reset(ctx, name):
    """Reset instance database to its template. Requires the instance to be stopped."""
    instance = _resolve_instance(ctx, name)
    workspace_root = _resolve_workspace(ctx)
    conf = _read_instance_conf(instance, workspace_root)
    if conf.database.template is None:
        click.echo("error: no template configured for this instance", err=True)
        sys.exit(1)
    if _is_running(instance, workspace_root):
        click.echo("error: stop the instance first", err=True)
        sys.exit(1)
    try:
        result = reset_db(
            name=conf.database.name,
            template=conf.database.template,
            pg_port=conf.database.pg_port,
            seed_script=None,
        )
    except Exception as e:
        workspace_log(workspace_root, "db_reset", instance=instance, template=conf.database.template, status="error", error=str(e))
        click.echo(f"error: {e}", err=True)
        sys.exit(1)
    workspace_log(workspace_root, "db_reset", instance=instance, template=result.restored_from, status="ok")
    msg = f"reset: {instance}  restored from {result.restored_from}"
    if result.warning:
        msg += f"\nwarn: {result.warning}"
    click.echo(msg)


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


@cli.command("unarchive")
@click.argument("name")
@click.option("--discard", is_flag=True, help="Remove the archive directory after restoring.")
@click.pass_context
def cmd_unarchive(ctx, name, discard):
    """Restore an instance from its archive."""
    workspace_root = _resolve_workspace(ctx)
    archive_dir = os.path.join(workspace_root, "_archive", name)
    archived_toml = os.path.join(archive_dir, "instance.toml")
    archived_dump = os.path.join(archive_dir, "db.dump")

    if not os.path.isdir(archive_dir):
        click.echo(f"error: no archive found for {name!r}", err=True)
        sys.exit(1)
    if not os.path.exists(archived_toml):
        click.echo(f"error: archive is missing instance.toml", err=True)
        sys.exit(1)

    instance_dir = os.path.join(workspace_root, "instances", name)
    if os.path.exists(instance_dir):
        click.echo(f"error: instances/{name}/ already exists — delete or rename it first", err=True)
        sys.exit(1)

    # Restore toml and materialise
    os.makedirs(instance_dir)
    import shutil
    from owm.archive import _strip_archived_sections
    dest_toml = os.path.join(instance_dir, "instance.toml")
    shutil.copy2(archived_toml, dest_toml)
    _strip_archived_sections(dest_toml)
    try:
        result = create_instance(name, workspace_root)
    except OwmError as e:
        click.echo(f"error: {e.args[0]} [{e.code}]", err=True)
        sys.exit(1)
    click.echo(f"  materialised {name}")

    # Restore database
    if os.path.exists(archived_dump):
        conf = _read_instance_conf(name, workspace_root)
        try:
            db_restore(
                instance=name, path=archived_dump, workspace_root=workspace_root,
                db_name=conf.database.name, pg_port=conf.database.pg_port, running=False,
            )
        except OwmError as e:
            click.echo(f"error: {e.args[0]} [{e.code}]", err=True)
            sys.exit(1)
        click.echo(f"  restored DB from archive dump")
    else:
        click.echo(f"  note: no db.dump in archive — DB not restored")

    if discard:
        shutil.rmtree(archive_dir)
        click.echo(f"  archive removed")

    click.echo(f"{name}  unarchived")


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
@click.option("--live", is_flag=True, help="Run live checks: DB reachable, HTTP port responds.")
@click.pass_context
def cmd_validate(ctx, name, live):
    """Validate instance configuration.

    Runs in tiers:
      static     — toml parses, repo names known in workspace.toml
      materialised — venv present, addon paths exist, instance.conf in sync
      live       — DB reachable, HTTP port responds (opt-in via --live)
    """
    instance = _resolve_instance(ctx, name)
    workspace_root = _resolve_workspace(ctx)

    errors = []
    warnings = []

    # --- Tier 1: static ---
    toml_path = os.path.join(workspace_root, "instances", instance, "instance.toml")
    try:
        with open(toml_path) as f:
            conf = parse_instance_config(f.read())
    except FileNotFoundError:
        click.echo(f"error: instance.toml not found — run owm create --toml-only first", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"error: instance.toml: {e}", err=True)
        sys.exit(1)

    ws_toml_path = os.path.join(workspace_root, "workspace.toml")
    try:
        with open(ws_toml_path) as f:
            ws_conf = parse_workspace_config(f.read())
        for repo_name in conf.repos:
            if repo_name not in ws_conf.repos:
                errors.append(f"repo {repo_name!r} not found in workspace.toml")
    except Exception as e:
        warnings.append(f"could not read workspace.toml: {e}")
        ws_conf = None

    # --- Tier 2: materialised ---
    instance_dir = os.path.join(workspace_root, "instances", instance)
    venv_dir = os.path.join(instance_dir, ".venv")
    if not os.path.isdir(venv_dir):
        warnings.append("venv not found — run owm create")

    if ws_conf:
        workspace_repos_meta = {
            n: {"has_addons": r.has_addons, "addons_paths": r.addons_paths}
            for n, r in ws_conf.repos.items()
        }
        instance_repos_dict = {
            n: {"shared": s.shared, "branch": s.branch}
            for n, s in conf.repos.items()
        }
        addons_paths = resolve_addons_path(
            workspace_repos=workspace_repos_meta,
            instance_repos=instance_repos_dict,
            workspace_root=workspace_root,
            instance_name=instance,
            instances_dir=ws_conf.defaults.instances_dir,
        )
        for ap in (addons_paths or []):
            if not os.path.isdir(ap):
                warnings.append(f"addon path missing: {ap}")
            elif not any(
                os.path.isfile(os.path.join(ap, d, "__manifest__.py"))
                for d in os.listdir(ap)
                if os.path.isdir(os.path.join(ap, d))
            ):
                warnings.append(f"addon path has no modules: {ap}")
    else:
        addons_paths = None

    conf_path = os.path.join(instance_dir, "instance.conf")
    if not os.path.isfile(conf_path):
        warnings.append("instance.conf missing — run owm create")
    else:
        log_path = os.path.join(instance_dir, "instance.log")
        expected_conf = generate_instance_conf(
            instance,
            conf.server.http_port,
            conf.server.gevent_port,
            conf.server.workers,
            db_name=conf.database.name,
            db_port=conf.database.pg_port,
            proxy_active=True,
            addons_path=addons_paths or None,
            logfile=log_path,
        )
        with open(conf_path) as f:
            on_disk = f.read()
        if on_disk != expected_conf:
            warnings.append("instance.conf is out of sync with instance.toml — run owm create")

    # --- Tier 3: live ---
    if live:
        pg_host = "/var/run/postgresql"
        reach = check_pg_reachability(pg_host, conf.database.pg_port)
        if reach.method == "error":
            errors.append(f"DB not reachable at port {conf.database.pg_port}")
        try:
            result = health_check(instance, workspace_root)
            if not result.get("http_ok"):
                warnings.append(f"HTTP port {conf.server.http_port} not responding")
        except Exception as e:
            warnings.append(f"live HTTP check failed: {e}")

    if errors:
        for e in errors:
            click.echo(f"error: {e}", err=True)
        for w in warnings:
            click.echo(f"warn:  {w}", err=True)
        sys.exit(1)
    elif warnings:
        for w in warnings:
            click.echo(f"warn:  {w}")
    else:
        suffix = "  (live)" if live else ""
        click.echo(f"{instance}  ok{suffix}")


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

def _collect_active_branches(workspace_root: str) -> dict[str, set[str]]:
    """Return {repo_name: {branch, ...}} by scanning all instance tomls."""
    active: dict[str, set[str]] = {}
    instances_dir = os.path.join(workspace_root, "instances")
    if not os.path.isdir(instances_dir):
        return active
    for entry in os.scandir(instances_dir):
        if not entry.is_dir():
            continue
        toml_path = os.path.join(entry.path, "instance.toml")
        if not os.path.exists(toml_path):
            continue
        try:
            with open(toml_path) as f:
                conf = parse_instance_config(f.read())
            for repo_name, spec in conf.repos.items():
                active.setdefault(repo_name, set()).add(spec.branch)
        except Exception:
            pass
    return active


@cli.command("branches")
@click.argument("repo", required=False)
@click.pass_context
def cmd_branches(ctx, repo):
    """List branches available in the workspace bare repos."""
    workspace_root = _resolve_workspace(ctx)
    repos_dir = os.path.join(workspace_root, "_repos")
    if not os.path.isdir(repos_dir):
        click.echo("error: _repos/ not found — run owm init first", err=True)
        sys.exit(1)
    names = sorted(
        d.removesuffix(".git")
        for d in os.listdir(repos_dir)
        if d.endswith(".git") and (repo is None or d == f"{repo}.git")
    )
    for name in names:
        bare = os.path.join(repos_dir, f"{name}.git")
        result = subprocess.run(
            ["git", "-C", bare, "branch", "--format=%(refname:short)"],
            capture_output=True, text=True,
        )
        branches = sorted(result.stdout.splitlines())
        click.echo(f"{name}:")
        for b in branches:
            click.echo(f"  {b}")


@cli.command("regen-conf")
@click.argument("name", required=False)
@click.pass_context
def cmd_regen_conf(ctx, name):
    """Regenerate instance.conf from current toml and workspace config."""
    instance = _resolve_instance(ctx, name)
    workspace_root = _resolve_workspace(ctx)
    conf = _read_instance_conf(instance, workspace_root)
    ws_toml_path = os.path.join(workspace_root, "workspace.toml")
    with open(ws_toml_path) as f:
        ws_conf = parse_workspace_config(f.read())
    workspace_repos_meta = {
        n: {"has_addons": r.has_addons, "addons_paths": r.addons_paths}
        for n, r in ws_conf.repos.items()
    }
    instance_repos_dict = {
        n: {"shared": s.shared, "branch": s.branch}
        for n, s in conf.repos.items()
    }
    addons_paths = resolve_addons_path(
        workspace_repos=workspace_repos_meta,
        instance_repos=instance_repos_dict,
        workspace_root=workspace_root,
        instance_name=instance,
        instances_dir=ws_conf.defaults.instances_dir,
    )
    log_path = os.path.join(workspace_root, "instances", instance, "instance.log")
    content = generate_instance_conf(
        instance,
        conf.server.http_port,
        conf.server.gevent_port,
        conf.server.workers,
        db_name=conf.database.name,
        db_port=conf.database.pg_port,
        proxy_active=True,
        addons_path=addons_paths or None,
        logfile=log_path,
    )
    conf_path = os.path.join(workspace_root, "instances", instance, "instance.conf")
    with open(conf_path, "w") as f:
        f.write(content)
    click.echo(f"{instance}  instance.conf regenerated")


@cli.command("fetch")
@click.pass_context
def cmd_fetch(ctx):
    """Fetch only branches active in instances (fast); skips unused remote branches."""
    workspace_root = _resolve_workspace(ctx)
    toml_path = os.path.join(workspace_root, "workspace.toml")
    with open(toml_path) as f:
        ws_conf = parse_workspace_config(f.read())
    repos = list(ws_conf.repos.keys())
    active_branches = _collect_active_branches(workspace_root)
    repos_with_updates = []
    unreachable = []
    for name in repos:
        bare_path = os.path.join(workspace_root, "_repos", f"{name}.git")
        if not os.path.isdir(bare_path):
            continue
        branches = sorted(active_branches.get(name, []))
        branch_hint = f" ({', '.join(branches)})" if branches else ""
        click.echo(f"  fetching {name}{branch_hint}...")
        try:
            updated = git_fetch_bare(bare_path, branches=branches or None)
        except OwmError as e:
            click.echo(f"  {name}: warning: {e.args[0]} [{e.code}]")
            unreachable.append(name)
            continue
        click.echo(f"  {name}: updated" if updated else f"  {name}: up to date")
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
