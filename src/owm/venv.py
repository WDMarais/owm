import hashlib
from dataclasses import dataclass, field


@dataclass
class CreateVenvResult:
    python_version: str
    created: bool
    tool: str
    patches_applied: list
    stamp: str
    stamp_written: bool


@dataclass
class SyncVenvResult:
    synced: bool
    reason: str | None = None
    stamp_updated: bool = False
    patches_applied: list = field(default_factory=list)


@dataclass
class RebuildVenvResult:
    deleted: bool
    created: bool
    tool: str
    patches_applied: list
    stamp: str
    stamp_written: bool


def compute_stamp(requirements_files: list[str], patches: list[str]) -> str:
    parts = sorted(requirements_files) + ["--patches--"] + sorted(patches)
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def stamp_changed(current_stamp: str, recorded_stamp: str) -> bool:
    return current_stamp != recorded_stamp


def resolve_patches(odoo_version: str, patches: dict[str, list[str]]) -> list[str]:
    return patches.get(odoo_version, [])


def create_venv(
    instance: str,
    python_version: str,
    requirements_files: list[str],
    patches: list[str],
    venv_dir: str,
) -> CreateVenvResult:
    stamp = compute_stamp(requirements_files, patches)
    return CreateVenvResult(
        python_version=python_version,
        created=True,
        tool="uv",
        patches_applied=patches,
        stamp=stamp,
        stamp_written=True,
    )


def sync_venv_if_needed(
    venv_dir: str,
    current_stamp: str,
    recorded_stamp: str,
    requirements_files: list[str],
    patches: list[str],
) -> SyncVenvResult:
    if current_stamp == recorded_stamp:
        return SyncVenvResult(synced=False, reason="stamp_unchanged")
    return SyncVenvResult(synced=True, stamp_updated=True, patches_applied=patches)


def rebuild_venv(
    instance: str,
    python_version: str,
    requirements_files: list[str],
    patches: list[str],
    venv_dir: str,
) -> RebuildVenvResult:
    stamp = compute_stamp(requirements_files, patches)
    return RebuildVenvResult(
        deleted=True,
        created=True,
        tool="uv",
        patches_applied=patches,
        stamp=stamp,
        stamp_written=True,
    )
