import sys
from pathlib import Path

import click

from owm.errors import OwmError
from owm.instance import new_instance, create_instance, list_running_instances, start_instance, stop_instance, health_check
from owm.operations import infer_instance_from_cwd


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
    return w if w else _find_workspace_root()


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


@cli.command("new")
@click.argument("name")
@click.argument("repos", nargs=-1, metavar="name=branch:base ...")
@click.pass_context
def cmd_new(ctx, name, repos):
    """Write instance.toml without materialising worktrees, DB, or ports."""
    repo_dict: dict[str, str] = {}
    for r in repos:
        if "=" not in r:
            raise click.UsageError(
                f"Invalid repo spec {r!r}; expected name=branch:base (e.g. odoo=main:shared)"
            )
        k, v = r.split("=", 1)
        repo_dict[k] = v

    workspace_root = _resolve_workspace(ctx)
    try:
        result = new_instance(name=name, repos=repo_dict, workspace_root=workspace_root)
        click.echo(result.toml_path)
    except OwmError as e:
        click.echo(f"error: {e.args[0]} [{e.code}]", err=True)
        sys.exit(1)


@cli.command("create")
@click.argument("name", required=False)
@click.pass_context
def cmd_create(ctx, name):
    """Materialise an instance from its instance.toml (creates worktrees, DB, proxy block)."""
    instance = _resolve_instance(ctx, name)
    workspace_root = _resolve_workspace(ctx)
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


@cli.command("status")
@click.argument("name", required=False)
@click.pass_context
def cmd_status(ctx, name):
    """Show health status of an instance."""
    instance = _resolve_instance(ctx, name)
    workspace_root = _resolve_workspace(ctx)
    h = health_check(instance, workspace_root)
    status = h["status"]
    if status == "stopped":
        click.echo(f"{instance}  stopped")
    elif status == "healthy":
        click.echo(f"{instance}  healthy  pid={h['pid']}  {h.get('url', '')}")
    elif status == "starting":
        click.echo(f"{instance}  starting  pid={h['pid']}")
    elif status == "unhealthy":
        click.echo(f"{instance}  unhealthy  pid={h['pid']}")
    elif status == "unmanaged":
        click.echo(f"{instance}  unmanaged process on port {h['port']}  pid={h['pid']}")
