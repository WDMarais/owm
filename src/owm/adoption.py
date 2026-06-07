from dataclasses import dataclass, field
from typing import Literal


@dataclass
class AdoptResult:
    status: Literal["needs_confirmation", "adopted"]
    pid: int | None = None
    pid_written_to_state: bool = False
    manageable: bool = False
    warning: str | None = None


@dataclass
class UnmanagedStatus:
    unmanaged: list
    instance_conflicts: list


def detect_unmanaged_processes(
    configured_instances: dict,
    running_processes: list[dict],
) -> list[dict]:
    configured_ports = {
        info.get("http_port")
        for info in configured_instances.values()
        if info.get("http_port")
    }
    return [p for p in running_processes if p.get("port") not in configured_ports]


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


def status_with_unmanaged(
    configured_instances: dict,
    running_processes: list[dict],
) -> UnmanagedStatus:
    port_to_instance = {
        info.get("http_port"): name
        for name, info in configured_instances.items()
        if info.get("http_port")
    }

    unmanaged = []
    instance_conflicts = []

    for proc in running_processes:
        port = proc.get("port")
        pid = proc.get("pid")
        matched = port_to_instance.get(port)

        if matched:
            instance_conflicts.append({
                "instance": matched,
                "unmanaged_pid": pid,
                "port": port,
                "message": f"unmanaged process on {matched!r} port — adopt or kill?",
            })
            unmanaged.append({**proc, "adopt_available": True})
        else:
            unmanaged.append({**proc, "adopt_available": False})

    return UnmanagedStatus(unmanaged=unmanaged, instance_conflicts=instance_conflicts)
