"""
There is no fixed body cap by default. Before a new body starts (a spawn, or a wake that needs a body) the server measures the
machine: the CPU busy cores (measured from the CPU tick counters, ``machine_stats/cpu_busy.py``; the load average only
when no tick delta exists yet, because it counts I/O-blocked threads and read far above the core count on a mostly idle machine), and the memory still available. When it cannot take another body the answer
is "system is pegged, try later" with a ``retry_after``. A measure that cannot be taken is unknown, and unknown never blocks
(the capacity governor's rule, ``docs/swarm-cards.md`` 10). The live body count rides along in the sentence so the caller sees
what is already running. Pure stdlib: ``os.getloadavg``, ``os.cpu_count``, ``sysctlbyname`` through ``ctypes`` on macOS and
``/proc/meminfo`` on Linux, so a check forks nothing.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys
from dataclasses import dataclass
from typing import Optional

import structlog

from src.core.machine_stats import cpu_busy

logger = structlog.get_logger()

LOAD_PER_CORE_MAX = 2.0
BUSY_PER_CORE_MAX = 0.9
MIN_AVAILABLE_MEMORY_PCT = 10.0
LOAD_RETRY_AFTER_S = 60
MEMORY_RETRY_AFTER_S = 120
PEGGED = "system is pegged, try later"


@dataclass(frozen=True)
class Machine:

    load1: Optional[float]
    load5: Optional[float]
    cores: Optional[int]
    available_memory_pct: Optional[float]
    mem_total_gb: Optional[float] = None
    busy1: Optional[float] = None
    busy5: Optional[float] = None


@dataclass(frozen=True)
class Reserve:

    cpu_pct: int
    mem_pct: int
    level: str = ""


def _darwin_memory_pct() -> Optional[float]:
    path = ctypes.util.find_library("c")
    if not path:
        return None
    libc = ctypes.CDLL(path, use_errno=True)
    value = ctypes.c_int(0)
    size = ctypes.c_size_t(ctypes.sizeof(value))
    if libc.sysctlbyname(b"kern.memorystatus_level", ctypes.byref(value), ctypes.byref(size), None, ctypes.c_size_t(0)) != 0:
        return None
    return float(value.value) if 0 <= value.value <= 100 else None


def _linux_memory_pct() -> Optional[float]:
    fields = {}
    with open("/proc/meminfo", encoding="ascii") as handle:
        for line in handle:
            name, _, rest = line.partition(":")
            if name in ("MemTotal", "MemAvailable"):
                fields[name] = int(rest.split()[0])
    total, available = fields.get("MemTotal"), fields.get("MemAvailable")
    return 100.0 * available / total if total and available is not None else None


def available_memory_pct() -> Optional[float]:
    try:
        if sys.platform == "darwin":
            return _darwin_memory_pct()
        if sys.platform.startswith("linux"):
            return _linux_memory_pct()
    except (OSError, ValueError, AttributeError) as exc:
        logger.warning("swarm_admission_memory_unreadable", error_type=type(exc).__name__)
    return None


def _total_memory_gb() -> Optional[float]:
    try:
        return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 1024.0 ** 3
    except (ValueError, OSError, AttributeError):
        return None


def measure() -> Machine:
    try:
        load1, load5, _ = os.getloadavg()
    except OSError:
        load1 = load5 = None
    cores = os.cpu_count()
    busy = cpu_busy.METER.busy_cores(cores)
    return Machine(load1, load5, cores, available_memory_pct(), _total_memory_gb(), busy["busy_1"], busy["busy_5"])


def reserve_refusal(machine: Machine, reserve: Reserve, est_cpu_cores: float, est_ram_gb: float) -> Optional[str]:
    name = f"its {reserve.cpu_pct}% {reserve.level.replace('_', ' ') or 'compute'} reserve"
    busy_now = machine.busy1 if machine.busy1 is not None else machine.load1
    if machine.cores and busy_now is not None:
        busy, line = min(busy_now, float(machine.cores)), machine.cores * (1 - reserve.cpu_pct / 100)
        if busy + est_cpu_cores > line:
            return (f"{PEGGED} (retry_after {LOAD_RETRY_AFTER_S} s): {busy:.1f} of {machine.cores} cores are busy and this job needs "
                    f"{est_cpu_cores:g}, past the {line:.1f} the owner leaves open after {name}")
    if machine.mem_total_gb and machine.available_memory_pct is not None:
        used = machine.mem_total_gb * (1 - machine.available_memory_pct / 100)
        line = machine.mem_total_gb * (1 - reserve.mem_pct / 100)
        if used + est_ram_gb > line:
            return (f"{PEGGED} (retry_after {MEMORY_RETRY_AFTER_S} s): {used:.1f} of {machine.mem_total_gb:.0f} GB are in use and this "
                    f"job needs {est_ram_gb:g}, past the {line:.1f} GB the owner leaves open after its {reserve.mem_pct}% memory reserve")
    return None


def refusal(machine: Machine, live_bodies: int, load_per_core_max: Optional[float] = None, *, reserve: Optional[Reserve] = None,
            est_cpu_cores: float = 0.5, est_ram_gb: float = 0.6) -> Optional[str]:
    if machine.cores and machine.busy1 is not None and machine.busy5 is not None:
        limit = load_per_core_max or BUSY_PER_CORE_MAX
        per1, per5 = machine.busy1 / machine.cores, machine.busy5 / machine.cores
        if per1 > limit and per5 > limit:
            return (f"{PEGGED} (retry_after {LOAD_RETRY_AFTER_S} s): the CPU is {per1 * 100:.0f}% busy over the last minute and "
                    f"{per5 * 100:.0f}% over five, above {limit * 100:g}% ({machine.busy1:.1f} of {machine.cores} cores busy, "
                    f"{live_bodies} agent bodies live)")
    elif machine.cores and machine.load1 is not None and machine.load5 is not None:
        limit = load_per_core_max or LOAD_PER_CORE_MAX
        per1, per5 = machine.load1 / machine.cores, machine.load5 / machine.cores
        if per1 > limit and per5 > limit:
            return (f"{PEGGED} (retry_after {LOAD_RETRY_AFTER_S} s): the load is {per1:.1f} per core over the last minute and "
                    f"{per5:.1f} over five, above {limit:g} ({machine.load1:.0f} on {machine.cores} cores, {live_bodies} agent bodies live)")
    if machine.available_memory_pct is not None and machine.available_memory_pct < MIN_AVAILABLE_MEMORY_PCT:
        return (f"{PEGGED} (retry_after {MEMORY_RETRY_AFTER_S} s): only {machine.available_memory_pct:.0f}% of memory is "
                f"available, under {MIN_AVAILABLE_MEMORY_PCT:g}% ({live_bodies} agent bodies live)")
    if reserve is not None:
        return reserve_refusal(machine, reserve, est_cpu_cores, est_ram_gb)
    return None
