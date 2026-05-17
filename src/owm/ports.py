from dataclasses import dataclass, field

from owm.errors import OwmError, PORT_EXHAUSTED, PORT_CONTESTED


@dataclass
class PortPair:
    http_port: int
    gevent_port: int


@dataclass
class PortConflict:
    instance: str | None = None
    running: bool | None = None
    requires_confirmation: bool | None = None
    pid: int | None = None
    name: str | None = None
    cmdline: str | None = None
    options: list[str] | None = None


class PortExhaustedError(OwmError):
    pass


@dataclass
class HonourResult:
    http_port: int
    gevent_port: int
    conflict: PortConflict | None = None


@dataclass
class StartPortResult:
    conflict: PortConflict | None = None
    new_http_port: int | None = None
    config_updated: bool = False
    http_port: int | None = None


@dataclass
class EvictResult:
    logged: bool
    old_port: int
    new_port: int


@dataclass
class EvictionCheck:
    alert: bool
    recommendation: str | None = None


def assign_port(pool: dict) -> PortPair:
    low, high = pool["range"]
    occupied: set[int] = pool.get("occupied", set())

    for n in range(low, high):
        if n not in occupied and (n + 1) not in occupied:
            return PortPair(http_port=n, gevent_port=n + 1)

    raise PortExhaustedError(
        f"[{PORT_EXHAUSTED}] port range {low}-{high} exhausted; "
        "archive or delete unused instances to free ports",
        code=PORT_EXHAUSTED,
    )


def honour_pinned_port(
    pinned_http: int,
    occupied: set[int],
    *,
    existing_instances: list[dict] | None = None,
) -> HonourResult:
    gevent = pinned_http + 1

    if pinned_http not in occupied:
        return HonourResult(http_port=pinned_http, gevent_port=gevent)

    if existing_instances:
        for inst in existing_instances:
            if inst.get("http_port") == pinned_http:
                if inst.get("running"):
                    raise OwmError(
                        f"port {pinned_http} is held by running instance {inst['instance']!r}",
                        code=PORT_CONTESTED,
                    )
                return HonourResult(
                    http_port=pinned_http,
                    gevent_port=gevent,
                    conflict=PortConflict(
                        instance=inst["instance"],
                        running=False,
                        requires_confirmation=True,
                    ),
                )

    return HonourResult(http_port=pinned_http, gevent_port=gevent)


def check_port_at_start(
    http_port: int,
    *,
    bound_by: dict | None = None,
    next_free_port: int | None = None,
    resolution: str | None = None,
) -> StartPortResult:
    if bound_by is None:
        return StartPortResult(http_port=http_port, config_updated=False)

    conflict = PortConflict(
        pid=bound_by.get("pid"),
        name=bound_by.get("name"),
        cmdline=bound_by.get("cmdline"),
        options=["kill", "reassign"],
    )

    if resolution == "reassign":
        return StartPortResult(
            new_http_port=next_free_port,
            config_updated=True,
        )
    if resolution == "kill":
        return StartPortResult(http_port=http_port, config_updated=False)

    return StartPortResult(conflict=conflict)


def evict_port(
    instance: str,
    old_port: int,
    new_port: int,
    reason: str,
) -> EvictResult:
    return EvictResult(logged=True, old_port=old_port, new_port=new_port)


def eviction_count_in_window(
    evictions: int,
    threshold: int,
    window_days: int,
) -> EvictionCheck:
    if evictions > threshold:
        return EvictionCheck(
            alert=True,
            recommendation="consider shifting port range to avoid repeated conflicts",
        )
    return EvictionCheck(alert=False)


def find_conflicting_process(port: int) -> dict | None:
    # I/O stub — real implementation queries psutil or `ss -tlnp` for pid/name/cmdline.
    return None


def get_eviction_log(log_path: str) -> list[dict]:
    # I/O stub — real implementation reads and parses the eviction log file at log_path.
    return []
