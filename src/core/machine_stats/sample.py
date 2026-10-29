
from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.core import host_metrics
from src.core.machine_stats import cpu_busy

CACHE_SECONDS: float = 2.0
MIN_CPU_INTERVAL_SECONDS: float = 1.0


class MachineSampler:

    def __init__(self, state_dir: Callable[[], str], *, clock: Callable[[], float] = time.monotonic,
        read_ticks: Callable[[], Optional[Tuple[int, int]]] = cpu_busy.read_ticks,
    ) -> None:
        self._state_dir = state_dir
        self._clock = clock
        self._lock = threading.Lock()
        self._cached: Optional[Dict[str, Any]] = None
        self._cached_at = 0.0
        self._read_ticks = read_ticks
        self._last_ticks: Optional[Tuple[float, int, int]] = None

    def reset_cpu_baseline(self) -> None:
        with self._lock:
            self._last_ticks = None

    def _cpu_percent(self) -> Optional[float]:
        ticks = self._read_ticks()
        now = self._clock()
        previous = self._last_ticks
        self._last_ticks = None if ticks is None else (now, ticks[0], ticks[1])
        if ticks is None or previous is None or now - previous[0] < MIN_CPU_INTERVAL_SECONDS or ticks[1] <= previous[2]:
            return None
        return 100.0 * (ticks[0] - previous[1]) / (ticks[1] - previous[2])

    def read(self, max_age: float = CACHE_SECONDS) -> Dict[str, Any]:
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
