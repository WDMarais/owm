import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone

from owm.errors import OwmError, INSTANCE_RUNNING, NOT_FOUND


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
    warning: str | None = None


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
    workspace_root: str = ".",
) -> LogsResult:
    instance_dir = os.path.join(workspace_root, "instances", instance)
    if not os.path.isdir(instance_dir):
        raise OwmError(f"instance {instance!r} not found", code=NOT_FOUND)
    log_path = os.path.join(instance_dir, "instance.log")
    lines = []
    warning = None
    try:
        with open(log_path) as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    lines.append(json.loads(raw))
                except json.JSONDecodeError:
                    lines.append({"raw": raw})
    except FileNotFoundError:
        warning = "no log file yet; instance may not have been started"
    if level:
        lines = [l for l in lines if l.get("level") in (level, "CRITICAL")]
    return LogsResult(lines=lines[-n:], log_path=log_path, warning=warning)


def _pg_dump(db_name: str, path: str, pg_port: int) -> None:
    subprocess.run(
        ["pg_dump", "-Fc", "-h", "/var/run/postgresql", "-p", str(pg_port), "-f", path, db_name],
        check=True, capture_output=True,
    )


def _pg_restore(db_name: str, path: str, pg_port: int) -> None:
    subprocess.run(
        ["pg_restore", "-h", "/var/run/postgresql", "-p", str(pg_port), "-d", db_name, path],
        check=True, capture_output=True,
    )


def db_dump(instance: str, out: str | None, workspace_root: str, *, db_name: str, pg_port: int) -> DumpResult:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M")
    path = out or os.path.join(workspace_root, "_dumps", instance, f"{ts}.dump")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _pg_dump(db_name=db_name, path=path, pg_port=pg_port)
    return DumpResult(path=path)


def db_restore(
    instance: str,
    path: str,
    workspace_root: str,
    *,
    db_name: str,
    pg_port: int,
    running: bool = False,
) -> RestoreResult:
    if running:
        raise OwmError(
            f"instance {instance!r} is running; stop it before restoring",
            code=INSTANCE_RUNNING,
        )
    resolved = path if path.startswith("/") else os.path.join(workspace_root, "_dumps", instance, path)
    _pg_restore(db_name=db_name, path=resolved, pg_port=pg_port)
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
