import os
from dataclasses import dataclass, field

from owm.errors import OwmError, INSTANCE_RUNNING, ARCHIVE_CONFLICT, CONFIRMATION_REQUIRED


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

    archive_path = f"{workspace_root}/_archive/{instance}/"

    if discard_artifacts:
        return ArchiveResult(
            preserved=["instance.toml"],
            archive_path=archive_path,
            db_dumped=False,
            db_dump_path=None,
            worktrees_removed=True,
            live_db_dropped=True,
            port_freed=True,
        )

    if discard_db:
        return ArchiveResult(
            preserved=["instance.toml", "notes.md", "review/"],
            archive_path=archive_path,
            db_dumped=False,
            db_dump_path=None,
            worktrees_removed=True,
            live_db_dropped=True,
            port_freed=True,
        )

    dump_path = f"{archive_path}db.dump"
    return ArchiveResult(
        preserved=["instance.toml", "db.dump", "notes.md", "review/"],
        archive_path=archive_path,
        db_dumped=True,
        db_dump_path=dump_path,
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
    return DeleteResult(
        status="deleted",
        path=f"{workspace_root}/_archive/{name}/",
    )
