
from __future__ import annotations

import os
import platform
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import structlog

from src.core import host_metrics

logger = structlog.get_logger()

PS_TIMEOUT_SECONDS: float = 3.0
CACHE_SECONDS: float = 2.0


def _linux_cpu_times() -> Optional[Tuple[int, int]]:
    try:
        with open("/proc/stat", "r", encoding="utf-8") as handle:
            fields = [int(part) for part in handle.readline().split()[1:]]
    except (OSError, ValueError):
        return None
    if len(fields) < 5:
        return None
    total = sum(fields[:8])
    idle = fields[3] + fields[4]
    return total - idle, total


def _darwin_cpu_percent() -> Optional[float]:
    try:
        done = subprocess.run(
            ["ps", "-A", "-o", "%cpu="], capture_output=True, text=True, timeout=PS_TIMEOUT_SECONDS, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("machine_stats_ps_failed", error=str(exc))
        return None
    if done.returncode != 0:
        return None
    try:
        total = sum(float(line) for line in done.stdout.split())
    except ValueError:
        return None
    return min(100.0, total / max(1, os.cpu_count() or 1))


class MachineSampler:

    def __init__(self, state_dir: Callable[[], str], *, clock: Callable[[], float] = time.monotonic) -> None:
        """Inputs: state_dir - returns the state directory whose volume's free space is reported;
        clock - monotonic seconds (tests pass a fake)."""
        self._state_dir = state_dir
        self._clock = clock
        self._lock = threading.Lock()
        self._cached: Optional[Dict[str, Any]] = None
        self._cached_at = 0.0
        self._last_times: Optional[Tuple[int, int]] = None

    def _cpu_percent(self) -> Optional[float]:
        system = platform.system()
        if system == "Darwin":
            return _darwin_cpu_percent()
        if system == "Linux":
            now = _linux_cpu_times()
            previous, self._last_times = self._last_times, now
            if now is None or previous is None or now[1] <= previous[1]:
                return None
            return 100.0 * (now[0] - previous[0]) / (now[1] - previous[1])
        return None

    def read(self, max_age: float = CACHE_SECONDS) -> Dict[str, Any]:
        """The current vitals, re-measured only when the cached one is older than ``max_age``.

        Output: dict ``{cpu_percent, cpu_count, memory_percent, memory_used_bytes, memory_total_bytes,
        disk_percent, disk_free_bytes, disk_total_bytes, load_1, load_5, load_15, uptime_seconds}``;
        any figure that could not be measured is None. Thread-safe.
        Example: MachineSampler(lambda: "/").read()["cpu_count"]  # 10
        """
        with self._lock:
            if self._cached is not None and self._clock() - self._cached_at < max_age:
                return dict(self._cached)
            memory = host_metrics.collect_memory()
            disk = host_metrics.collect_disk(self._state_dir())
            load = host_metrics.collect_load()
            cpu = self._cpu_percent()
            reading: Dict[str, Any] = {
                "cpu_percent": None if cpu is None else round(cpu, 1),
                "cpu_count": os.cpu_count() or None,
                "memory_percent": memory.get("used_percent") if memory["available"] else None,
                "memory_used_bytes": memory.get("used_bytes") if memory["available"] else None,
                "memory_total_bytes": memory.get("total_bytes") if memory["available"] else None,
                "disk_percent": disk.get("used_percent") if disk["available"] else None,
                "disk_free_bytes": disk.get("free_bytes") if disk["available"] else None,
                "disk_total_bytes": disk.get("total_bytes") if disk["available"] else None,
                "load_1": load.get("load_1") if load["available"] else None,
                "load_5": load.get("load_5") if load["available"] else None,
                "load_15": load.get("load_15") if load["available"] else None,
                "uptime_seconds": host_metrics.collect_host()["uptime_seconds"],
            }
            self._cached, self._cached_at = reading, self._clock()
            return dict(reading)


CHANGE_STEPS: Tuple[Tuple[str, float], ...] = (
    ("cpu_percent", 3.0),
    ("memory_percent", 1.0),
    ("disk_percent", 0.5),
    ("load_1", 0.25),
)


def signature(reading: Dict[str, Any]) -> List[Optional[int]]:
    out: List[Optional[int]] = []
    for key, step in CHANGE_STEPS:
        value = reading.get(key)
        out.append(None if value is None else int(value // step))
    return out
