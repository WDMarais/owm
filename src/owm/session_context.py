import os
from dataclasses import dataclass, field


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


def get_context_files(
    instance_dir: str,
    *,
    files_present: list[str] | None = None,
) -> ContextFiles:
    if files_present is not None:
        names = set(files_present)
        setup_md = "setup.md" if "setup.md" in names else None
        context_md = "context.md" if "context.md" in names else None
        notes_md = "notes.md" if "notes.md" in names else None
        snapshots = sorted(f for f in files_present if f.startswith("review/"))
    else:
        setup_md = _file_or_none(instance_dir, "setup.md")
        context_md = _file_or_none(instance_dir, "context.md")
        notes_md = _file_or_none(instance_dir, "notes.md")
        review_dir = os.path.join(instance_dir, "review")
        try:
            entries = os.listdir(review_dir)
            snapshots = sorted(
                f"review/{e}" for e in entries if e.endswith(".md")
            )
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
    *,
    existing_files: list[str] | None = None,
) -> SnapshotResult:
    review_dir = os.path.join(instance_dir, "review")
    base = f"{date}-{trigger}"

    if existing_files is not None:
        existing_rels = set(existing_files)
        rel = f"review/{base}.md"
        if rel in existing_rels:
            suffix = 2
            while f"review/{base}-{suffix}.md" in existing_rels:
                suffix += 1
            rel = f"review/{base}-{suffix}.md"
        abs_path = os.path.join(instance_dir, rel)
    else:
        abs_path = os.path.join(review_dir, f"{base}.md")
        if os.path.exists(abs_path):
            suffix = 2
            while os.path.exists(os.path.join(review_dir, f"{base}-{suffix}.md")):
                suffix += 1
            abs_path = os.path.join(review_dir, f"{base}-{suffix}.md")

    try:
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
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


def status_has_setup_md(
    instance: str,
    instance_dir: str,
    setup_md_present: bool,
) -> StatusResult:
    return StatusResult(
        setup_md_present=setup_md_present,
        surfaced_in_status=setup_md_present,
    )


def _file_or_none(instance_dir: str, filename: str) -> str | None:
    path = os.path.join(instance_dir, filename)
    return path if os.path.exists(path) else None
