from dataclasses import dataclass
from typing import Literal


@dataclass
class AdoptResult:
    status: Literal["needs_confirmation", "adopted"]
    pid: int | None = None
    pid_written_to_state: bool = False
    manageable: bool = False
    warning: str | None = None


def adopt_process(
    instance: str,
    pid: int,
    configured_port: int,
    process_port: int,
    *,
    force: bool = False,
) -> AdoptResult:
    if configured_port != process_port and not force:
        return AdoptResult(
            status="needs_confirmation",
            pid=pid,
            warning=(
                f"process port {process_port} does not match configured port "
                f"{configured_port} for {instance!r}; use --force to adopt anyway"
            ),
        )
    return AdoptResult(
        status="adopted",
        pid=pid,
        pid_written_to_state=True,
        manageable=True,
    )
