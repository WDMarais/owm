import hashlib
import os
import shutil
import subprocess
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


def _uv_venv(python_version: str, venv_dir: str) -> None:
    subprocess.run(
        ["uv", "venv", "--python", python_version, venv_dir],
        check=True, capture_output=True,
    )


def _uv_pip_install(venv_dir: str, requirements_files: list[str]) -> None:
    python = os.path.join(venv_dir, "bin", "python")
    for req in requirements_files:
        subprocess.run(
            ["uv", "pip", "install", "--python", python, "-r", req],
            check=True, capture_output=True,
        )


def _write_stamp(venv_dir: str, stamp: str) -> None:
    with open(os.path.join(venv_dir, ".owm_stamp"), "w") as f:
        f.write(stamp)


def _read_stamp(venv_dir: str) -> str | None:
    try:
        with open(os.path.join(venv_dir, ".owm_stamp")) as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


def _delete_venv(venv_dir: str) -> None:
    shutil.rmtree(venv_dir, ignore_errors=True)


def _file_fingerprint(path: str) -> str:
    """`path:sha256(content)` — a missing file hashes as empty content.

    Content-sensitive so an in-place edit to a requirements/patch file (same
    path) moves the stamp, while a no-op git checkout that rewrites the file
    with identical content does not. Path stays in the fingerprint so a rename
    or a swap to a differently-named variant still registers."""
    try:
        with open(path, "rb") as f:
            body = f.read()
    except OSError:
        body = b""
    return f"{path}:{hashlib.sha256(body).hexdigest()}"


def compute_stamp(requirements_files: list[str], patches: list[str]) -> str:
    parts = (
        [_file_fingerprint(f) for f in sorted(requirements_files)]
        + ["--patches--"]
        + [_file_fingerprint(p) for p in sorted(patches)]
    )
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def resolve_patches(odoo_version: str, patches: dict[str, list[str]]) -> list[str]:
    return patches.get(odoo_version, [])


def create_venv(
    instance: str,
    python_version: str,
    requirements_files: list[str],
    patches: list[str],
    venv_dir: str,
) -> CreateVenvResult:
    _uv_venv(python_version, venv_dir)
    _uv_pip_install(venv_dir, requirements_files + patches)
    stamp = compute_stamp(requirements_files, patches)
    _write_stamp(venv_dir, stamp)
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
    _uv_pip_install(venv_dir, requirements_files + patches)
    _write_stamp(venv_dir, current_stamp)
    return SyncVenvResult(synced=True, stamp_updated=True, patches_applied=patches)


def reconcile_venv(
    venv_dir: str,
    requirements_files: list[str],
    patches: list[str],
) -> SyncVenvResult:
    """Reconcile an existing venv with the currently-collected requirements.

    Reads the venv's own recorded stamp (rather than making the caller thread it
    through), so callers on the create/start paths can keep an existing venv in
    step with a broadened or changed requirement set without re-deriving stamps.
    """
    current = compute_stamp(requirements_files, patches)
    recorded = _read_stamp(venv_dir) or ""
    return sync_venv_if_needed(venv_dir, current, recorded, requirements_files, patches)


def rebuild_venv(
    instance: str,
    python_version: str,
    requirements_files: list[str],
    patches: list[str],
    venv_dir: str,
) -> RebuildVenvResult:
    _delete_venv(venv_dir)
    _uv_venv(python_version, venv_dir)
    _uv_pip_install(venv_dir, requirements_files + patches)
    stamp = compute_stamp(requirements_files, patches)
    _write_stamp(venv_dir, stamp)
    return RebuildVenvResult(
        deleted=True,
        created=True,
        tool="uv",
        patches_applied=patches,
        stamp=stamp,
        stamp_written=True,
    )
