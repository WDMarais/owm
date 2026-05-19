import sys
from pathlib import Path

import click

from owm.errors import OwmError
from owm.instance import new_instance, list_running_instances


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
