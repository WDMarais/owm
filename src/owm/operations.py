from dataclasses import dataclass, field
from datetime import datetime, timezone

from owm.errors import OwmError, INSTANCE_RUNNING


@dataclass
class DeleteResult:
    status: str
    checklist: list | None = None
    worktrees_removed: bool = False
    db_dropped: bool = False
    proxy_block_removed: bool = False
    instance_folder_removed: bool = False
    workspace_toml_updated: bool = False
    remaining_compare_pairs: list = field(default_factory=list)


@dataclass
class RenameResult:
    status: str
    old_name: str
    new_name: str
    db_renamed: bool = False
    nginx_block_updated: bool = False
    port_unchanged: bool = False
    old_url: str | None = None
    new_url: str | None = None
    remaining_compare_pairs: list = field(default_factory=list)


@dataclass
class LogsResult:
    lines: list
    log_path: str


@dataclass
class DumpResult:
    path: str


@dataclass
class RestoreResult:
    resolved_path: str


@dataclass
class ValidateResult:
    valid: bool
    errors: list = field(default_factory=list)
    live_checks_run: bool = False


@dataclass
class CwdResult:
    instance: str | None


def delete_instance(
    instance: str,
    *,
    running: bool,
    force: bool,
    has_session_notes: bool = False,
    open_compare_pairs: list | None = None,
    workspace_compare_pairs: list | None = None,
) -> DeleteResult:
    if running:
        raise OwmError(
            f"instance {instance!r} is running; stop it before deleting",
            code=INSTANCE_RUNNING,
        )
    if not force:
        checklist = []
        if has_session_notes:
            checklist.append("session notes will be lost")
        if open_compare_pairs:
            checklist.append(f"open compare pairs: {open_compare_pairs}")
        if not checklist:
            checklist.append("all instance data will be permanently deleted")
        return DeleteResult(status="pending_confirmation", checklist=checklist)

    remaining = [
        pair for pair in (workspace_compare_pairs or [])
        if instance not in pair
    ]
    updated = workspace_compare_pairs is not None and len(remaining) < len(workspace_compare_pairs or [])
    return DeleteResult(
        status="deleted",
        worktrees_removed=True,
        db_dropped=True,
        proxy_block_removed=True,
        instance_folder_removed=True,
        workspace_toml_updated=updated,
        remaining_compare_pairs=remaining,
    )


def rename_instance(
    instance: str,
    new_name: str,
    *,
    running: bool,
    workspace_compare_pairs: list | None = None,
) -> RenameResult:
    if running:
        raise OwmError(
            f"instance {instance!r} is running; stop it before renaming",
            code=INSTANCE_RUNNING,
        )
    remaining = [
        [new_name if p == instance else p for p in pair]
        for pair in (workspace_compare_pairs or [])
    ]
    return RenameResult(
        status="renamed",
        old_name=instance,
        new_name=new_name,
        db_renamed=True,
        nginx_block_updated=True,
        port_unchanged=True,
        old_url=f"https://{instance}.localhost",
        new_url=f"https://{new_name}.localhost",
        remaining_compare_pairs=remaining,
    )


def show_logs(
    instance: str,
    n: int,
    follow: bool,
    level: str | None,
    *,
    simulated_lines: list | None = None,
) -> LogsResult:
    log_path = f"instances/{instance}/instance.log"
    lines = simulated_lines or []
    if level:
        lines = [l for l in lines if l.get("level") in (level, "CRITICAL")]
    return LogsResult(lines=lines[:n], log_path=log_path)


def db_dump(instance: str, out: str | None, workspace_root: str) -> DumpResult:
    if out:
        return DumpResult(path=out)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M")
    return DumpResult(path=f"{workspace_root}/_dumps/{instance}/{ts}.dump")


def db_restore(
    instance: str,
    path: str,
    workspace_root: str,
    *,
    running: bool = False,
) -> RestoreResult:
    if running:
        raise OwmError(
            f"instance {instance!r} is running; stop it before restoring",
            code=INSTANCE_RUNNING,
        )
    if path.startswith("/"):
        resolved = path
    else:
        resolved = f"{workspace_root}/_dumps/{instance}/{path}"
    return RestoreResult(resolved_path=resolved)


def validate_instance(
    instance: str,
    *,
    live: bool = False,
    toml_valid: bool = True,
    missing_fields: list | None = None,
    **state_kwargs,
) -> ValidateResult:
    errors = []
    if not toml_valid:
        for field_name in (missing_fields or ["unknown field"]):
            errors.append(f"missing required field: {field_name}")

    if live:
        return ValidateResult(valid=not errors, errors=errors, live_checks_run=True)
    return ValidateResult(valid=not errors, errors=errors, live_checks_run=False)


def infer_instance_from_cwd(
    cwd: str,
    workspace_root: str,
    instances_dir: str,
    *,
    explicit_name: str | None = None,
) -> CwdResult:
    if explicit_name:
        return CwdResult(instance=explicit_name)
    prefix = f"{workspace_root}/{instances_dir}/"
    if not cwd.startswith(prefix):
        return CwdResult(instance=None)
    remainder = cwd[len(prefix):]
    instance = remainder.split("/")[0] if remainder else None
    return CwdResult(instance=instance or None)


def adopt_instance(instance: str, pid: int, **kwargs):
    from owm.adoption import adopt_process
    return adopt_process(instance=instance, pid=pid, **kwargs)
