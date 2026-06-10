import os
from dataclasses import dataclass


@dataclass
class ContextFiles:
    setup_md: str | None
    context_md: str | None
    notes_md: str | None
    review_snapshots: list[str]
    latest_review: str | None
    happy_path: bool


@dataclass
class SnapshotResult:
    path: str


@dataclass
class AgentContext:
    context: str
    sources: dict


@dataclass
class StatusResult:
    setup_md_present: bool
    surfaced_in_status: bool


def get_context_files(instance_dir: str) -> ContextFiles:
    setup_md = _file_or_none(instance_dir, "setup.md")
    context_md = _file_or_none(instance_dir, "context.md")
    notes_md = _file_or_none(instance_dir, "notes.md")
    review_dir = os.path.join(instance_dir, "review")
    try:
        entries = os.listdir(review_dir)
        snapshots = sorted(f"review/{e}" for e in entries if e.endswith(".md"))
    except OSError:
        snapshots = []

    latest = snapshots[-1] if snapshots else None
    return ContextFiles(
        setup_md=setup_md,
        context_md=context_md,
        notes_md=notes_md,
        review_snapshots=snapshots,
        latest_review=latest,
        happy_path=setup_md is None,
    )


def write_review_snapshot(
    instance: str,
    instance_dir: str,
    trigger: str,
    date: str,
    content: str,
) -> SnapshotResult:
    review_dir = os.path.join(instance_dir, "review")
    base = f"{date}-{trigger}"
    abs_path = os.path.join(review_dir, f"{base}.md")
    if os.path.exists(abs_path):
        suffix = 2
        while os.path.exists(os.path.join(review_dir, f"{base}-{suffix}.md")):
            suffix += 1
        abs_path = os.path.join(review_dir, f"{base}-{suffix}.md")

    try:
        os.makedirs(review_dir, exist_ok=True)
        with open(abs_path, "w") as f:
            f.write(content)
    except OSError:
        pass

    return SnapshotResult(path=abs_path)


def build_agent_context(
    instance: str,
    *,
    role: str | None,
    workspace_boilerplate: str,
    instance_notes: str | None,
    review_files: list[str],
    setup_md: str | None,
    review_include: str | int = "latest",
) -> AgentContext:
    if review_include != "latest":
        raise NotImplementedError(
            f"review_include={review_include!r} is not implemented; "
            "supported values: 'latest'. Planned: 'all', int (past N)."
        )

    parts = [workspace_boilerplate]

    if setup_md is not None:
        parts.append(setup_md)

    if instance_notes is not None:
        parts.append(instance_notes)

    if review_files:
        latest = sorted(review_files)[-1]
        parts.append(latest)

    return AgentContext(
        context="\n\n".join(parts),
        sources={
            "role_template": role,
            "workspace": workspace_boilerplate,
            "instance": instance_notes,
        },
    )


def status_has_setup_md(instance: str, instance_dir: str) -> StatusResult:
    present = os.path.exists(os.path.join(instance_dir, "setup.md"))
    return StatusResult(setup_md_present=present, surfaced_in_status=present)


def _file_or_none(instance_dir: str, filename: str) -> str | None:
    path = os.path.join(instance_dir, filename)
    return path if os.path.exists(path) else None
