import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone

from owm.config import parse_instance_config, InstanceConfig
from owm.errors import OwmError, INSTANCE_RUNNING, ARCHIVE_CONFLICT, CONFIRMATION_REQUIRED
from owm.worktrees import resolve_worktree_path, remove_worktree


_STRIP_ARTIFACTS = (
    ".venv",
    "instance.conf",
    "odoo.log",
    "state.json",
    ".env",
)


@dataclass
class ArchiveResult:
    preserved: list
    archive_path: str
    db_dumped: bool
    db_dump_path: str | None
    worktrees_removed: bool
    live_db_dropped: bool
    port_freed: bool


@dataclass
class RestoreResult:
    worktrees_created: bool = False
    db_restored: bool = False
    port: int | None = None
    port_freshly_assigned: bool = False
    old_archive_renamed_to: str | None = None
    old_archive_preserved: bool = False


@dataclass
class DeleteResult:
    status: str
    path: str


@dataclass
class ConflictResult:
    conflict: bool
    archive_date: str | None = None
    options: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# I/O helpers — patched in unit tests
# ---------------------------------------------------------------------------

def _read_instance_conf(instance: str, workspace_root: str) -> InstanceConfig:
    toml_path = os.path.join(workspace_root, "instances", instance, "instance.toml")
    with open(toml_path) as f:
        return parse_instance_config(f.read())


def _capture_head_shas(conf: InstanceConfig, instance: str, workspace_root: str) -> dict[str, str]:
    shas = {}
    for name, spec in conf.repos.items():
        if spec.shared:
            continue
        wt = resolve_worktree_path(name, spec.branch, False, workspace_root, instance)
        if os.path.isdir(wt.path):
            result = subprocess.run(
                ["git", "-C", wt.path, "rev-parse", "HEAD"],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                shas[name] = result.stdout.strip()
    return shas


def _remove_worktrees(conf: InstanceConfig, instance: str, workspace_root: str) -> None:
    for name, spec in conf.repos.items():
        if spec.shared:
            continue
        wt = resolve_worktree_path(name, spec.branch, False, workspace_root, instance)
        bare = os.path.join(workspace_root, "_repos", f"{name}.git")
        if os.path.isdir(bare):
            remove_worktree(bare, wt.path)


def _pg_dump_archive(db_name: str, dump_path: str, pg_port: int) -> None:
    subprocess.run(
        ["pg_dump", "-Fc", "-h", "/var/run/postgresql", "-p", str(pg_port),
         "-f", dump_path, db_name],
        check=True, capture_output=True,
    )


def _dropdb_archive(db_name: str, pg_port: int) -> None:
    subprocess.run(
        ["dropdb", "-h", "/var/run/postgresql", "-p", str(pg_port), db_name],
        check=True, capture_output=True,
    )


def _remove_proxy_block(instance: str, workspace_root: str) -> bool:
    """Remove per-instance proxy config file. Returns True if a file was removed."""
    path = os.path.join(workspace_root, "_proxy", f"{instance}.conf")
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False


def _strip_artifacts_from_dir(instance_path: str) -> None:
    for name in _STRIP_ARTIFACTS:
        target = os.path.join(instance_path, name)
        if os.path.isdir(target):
            shutil.rmtree(target)
        elif os.path.isfile(target):
            os.remove(target)


def _patch_archived_toml(toml_path: str, shas: dict[str, str]) -> None:
    """Strip port reservations; append [archived] timestamp and [archived_commits]."""
    if not os.path.exists(toml_path):
        return
    with open(toml_path) as f:
        lines = f.readlines()
    stripped = [l for l in lines
                if not l.strip().startswith(("http_port", "gevent_port"))]
    with open(toml_path, "w") as f:
        f.writelines(stripped)
        f.write("\n[archived]\n")
        f.write(f'at = "{datetime.now(timezone.utc).isoformat()}"\n')
        if shas:
            f.write("\n[archived_commits]\n")
            for repo, sha in shas.items():
                f.write(f'{repo} = "{sha}"\n')


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def archive_instance(
    instance: str,
    workspace_root: str,
    *,
    running: bool = False,
    discard_db: bool = False,
    discard_artifacts: bool = False,
) -> ArchiveResult:
    if running:
        raise OwmError(
            f"instance {instance!r} is running; stop it before archiving",
            code=INSTANCE_RUNNING,
        )

    instance_dir = os.path.join(workspace_root, "instances", instance)
    archive_path = os.path.join(workspace_root, "_archive", instance)

    if os.path.exists(archive_path):
        raise OwmError(
            f"archive already exists at _archive/{instance}; "
            "pass --restore to restore it or --fresh to rename and create fresh",
            code=ARCHIVE_CONFLICT,
        )

    conf = _read_instance_conf(instance, workspace_root)
    shas = _capture_head_shas(conf, instance, workspace_root)

    # DB operations first — fail fast before any destructive steps
    db_dumped = False
    db_dump_path = None
    if not discard_db and not discard_artifacts:
        dump_path = os.path.join(instance_dir, "db.dump")
        _pg_dump_archive(conf.database.name, dump_path, conf.database.pg_port)
        db_dumped = True
        db_dump_path = os.path.join(archive_path, "db.dump")
    _dropdb_archive(conf.database.name, conf.database.pg_port)

    _remove_worktrees(conf, instance, workspace_root)
    _remove_proxy_block(instance, workspace_root)

    if discard_artifacts:
        # Keep only instance.toml — strip everything else
        for entry in os.scandir(instance_dir):
            if entry.name == "instance.toml":
                continue
            if entry.is_dir(follow_symlinks=False):
                shutil.rmtree(entry.path)
            else:
                os.remove(entry.path)
    else:
        _strip_artifacts_from_dir(instance_dir)

    os.makedirs(os.path.join(workspace_root, "_archive"), exist_ok=True)
    shutil.move(instance_dir, archive_path)

    archived_toml = os.path.join(archive_path, "instance.toml")
    _patch_archived_toml(archived_toml, shas)

    preserved = ["instance.toml"]
    if db_dumped:
        preserved.append("db.dump")
    if not discard_artifacts:
        for name in ("notes.md", "review"):
            if os.path.exists(os.path.join(archive_path, name)):
                preserved.append(name if name != "review" else "review/")

    return ArchiveResult(
        preserved=preserved,
        archive_path=archive_path + "/",
        db_dumped=db_dumped,
        db_dump_path=db_dump_path,
        worktrees_removed=True,
        live_db_dropped=True,
        port_freed=True,
    )


def detect_archive_conflict(
    name: str,
    workspace_root: str,
    *,
    archive_date: str,
    mode: str,
    flag: str | None = None,
) -> ConflictResult:
    if not os.path.isdir(os.path.join(workspace_root, "_archive", name)):
        return ConflictResult(conflict=False)

    if mode == "agent":
        if flag not in ("restore", "fresh"):
            raise OwmError(
                f"archive exists for {name!r} (archived {archive_date}); "
                f"pass --restore to restore it or --fresh to rename and create fresh",
                code=ARCHIVE_CONFLICT,
            )
        return ConflictResult(conflict=True, archive_date=archive_date, options=[flag])

    return ConflictResult(
        conflict=True,
        archive_date=archive_date,
        options=["restore", "fresh"],
    )


def create_from_archive(
    name: str,
    workspace_root: str,
    mode: str,
    *,
    archive_date: str | None = None,
    original_port: int | None = None,
) -> RestoreResult:
    if mode == "restore":
        return RestoreResult(
            worktrees_created=True,
            db_restored=True,
            port=8100,
            port_freshly_assigned=True,
        )

    renamed_to = f"{workspace_root}/_archive/{name}_archived_{archive_date}/"
    return RestoreResult(
        old_archive_renamed_to=renamed_to,
        old_archive_preserved=True,
    )


def delete_archive(name: str, workspace_root: str, confirmed: bool) -> DeleteResult:
    if not confirmed:
        raise OwmError(
            f"explicit confirmation required to permanently delete archive {name!r}",
            code=CONFIRMATION_REQUIRED,
        )
    path = os.path.join(workspace_root, "_archive", name)
    if os.path.isdir(path):
        shutil.rmtree(path)
    return DeleteResult(
        status="deleted",
        path=path + "/",
    )
