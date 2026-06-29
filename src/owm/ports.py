import json
from dataclasses import dataclass

import psutil

from owm.errors import OwmError, PORT_RANGE_EXHAUSTED, PORT_CONTESTED


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
        f"[{PORT_RANGE_EXHAUSTED}] port range {low}-{high} exhausted; "
        "archive or delete unused instances to free ports",
        code=PORT_RANGE_EXHAUSTED,
    )


@dataclass
class PortPlan:
    candidates: list[PortPair]
    free_pairs: int
    nominal_pairs: int
    warnings: list[dict]
    exhausted: bool


# Below this many free pairs remaining, plan_ports flags low_capacity so the
# range can be widened before allocation starts failing.
_LOW_PORT_CAPACITY = 5


def _greedy_pair_count(occupied: set[int], low: int, high: int) -> int:
    """How many more non-overlapping http/gevent pairs the allocator could place in
    [low, high) given `occupied` — i.e. how many more instances fit. Mirrors
    assign_port's stride-1 scan: take a pair at n and skip n+1, else advance by one."""
    count = 0
    n = low
    while n < high:
        if n not in occupied and (n + 1) not in occupied:
            count += 1
            n += 2
        else:
            n += 1
    return count


def plan_ports(allocations: list[dict], port_range: list[int], count: int = 1) -> PortPlan:
    """Pure preview of the next free port pair(s) plus allocation-health warnings.

    `allocations` is one dict per configured instance: {instance, http_port,
    gevent_port}. No I/O — the caller gathers allocations from the instances dir and
    the range from workspace config. Warnings surfaced:
      - collision: a port claimed by more than one instance
      - odd_http_base: an instance whose http_port is odd, off the even pair lattice
      - low_capacity / range_exhausted: capacity running out
    """
    low, high = port_range
    occupied: set[int] = set()
    owners: dict[int, list[str]] = {}
    for a in allocations:
        for p in (a.get("http_port"), a.get("gevent_port")):
            if p:
                occupied.add(p)
                owners.setdefault(p, []).append(a["instance"])

    warnings: list[dict] = []
    for port in sorted(owners):
        if len(owners[port]) > 1:
            warnings.append({"type": "collision", "port": port,
                             "instances": sorted(owners[port])})
    for a in allocations:
        http = a.get("http_port")
        if http and http % 2 == 1:
            warnings.append({"type": "odd_http_base", "instance": a["instance"],
                             "http_port": http})

    candidates: list[PortPair] = []
    work = set(occupied)
    exhausted = False
    for _ in range(max(count, 1)):
        try:
            pair = assign_port({"range": [low, high], "occupied": work})
        except PortExhaustedError:
            exhausted = True
            break
        candidates.append(pair)
        work.add(pair.http_port)
        work.add(pair.gevent_port)

    free_pairs = _greedy_pair_count(occupied, low, high)
    nominal_pairs = _greedy_pair_count(set(), low, high)
    if exhausted:
        warnings.append({"type": "range_exhausted", "range": [low, high]})
    elif free_pairs <= _LOW_PORT_CAPACITY:
        warnings.append({"type": "low_capacity", "free_pairs": free_pairs})

    return PortPlan(candidates=candidates, free_pairs=free_pairs,
                    nominal_pairs=nominal_pairs, warnings=warnings, exhausted=exhausted)


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
    *,
    log_path: str | None = None,
) -> EvictResult:
    if log_path is not None:
        entry = {"instance": instance, "old_port": old_port, "new_port": new_port, "reason": reason}
        with open(log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
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
    for conn in psutil.net_connections(kind="tcp"):
        if conn.laddr.port == port and conn.status == "LISTEN":
            try:
                proc = psutil.Process(conn.pid)
                return {
                    "pid": conn.pid,
                    "name": proc.name(),
                    "cmdline": " ".join(proc.cmdline()),
                }
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return {"pid": conn.pid, "name": None, "cmdline": None}
    return None


def listeners_on_ports(ports: set[int]) -> dict[int, dict]:
    """One net_connections snapshot → {port: {pid, name, cmdline}} for each given
    port currently in LISTEN. The many-port form of find_conflicting_process, for
    when a whole set of ports is checked at once (odoo-ps squatter detection) rather
    than one scan per port — one table read instead of N."""
    holders: dict[int, dict] = {}
    for conn in psutil.net_connections(kind="tcp"):
        port = conn.laddr.port
        if conn.status != "LISTEN" or port not in ports or port in holders:
            continue
        try:
            proc = psutil.Process(conn.pid)
            holders[port] = {"pid": conn.pid, "name": proc.name(),
                             "cmdline": " ".join(proc.cmdline())}
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            holders[port] = {"pid": conn.pid, "name": None, "cmdline": None}
    return holders


def find_port_for_pid(pid: int) -> int | None:
    for conn in psutil.net_connections(kind="tcp"):
        if conn.pid == pid and conn.status == "LISTEN":
            return conn.laddr.port
    return None


def get_eviction_log(log_path: str) -> list[dict]:
    try:
        with open(log_path) as f:
            return [json.loads(line) for line in f if line.strip()]
    except OSError:
        return []
