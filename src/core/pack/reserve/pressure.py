
from __future__ import annotations

import ctypes
import ctypes.util
import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import structlog

from src.core.pack.reserve import holds as holds_mod
from src.core.pack.reserve.throttle import CLEAR_AFTER_SECONDS, CLEAR_MARGIN

logger = structlog.get_logger()

RUN_QUEUE_ON = 1.5
RUN_QUEUE_OFF = 1.2
MEM_NORMAL, MEM_WARN, MEM_CRITICAL = "normal", "warn", "critical"
_DARWIN_LEVELS = {1: MEM_NORMAL, 2: MEM_WARN, 4: MEM_CRITICAL}
_PSI_PATH = "/proc/pressure/memory"
_HOURS_KEPT = 48


def _darwin_level() -> Optional[int]:
    path = ctypes.util.find_library("c")
    if not path:
        return None
    libc = ctypes.CDLL(path, use_errno=True)
    value = ctypes.c_int(0)
    size = ctypes.c_size_t(ctypes.sizeof(value))
    if libc.sysctlbyname(b"kern.memorystatus_vm_pressure_level", ctypes.byref(value), ctypes.byref(size), None, ctypes.c_size_t(0)) != 0:
        return None
    return int(value.value)


def parse_psi(text: str) -> Optional[str]:
    figures: Dict[str, float] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[0] not in ("some", "full"):
            continue
        for part in parts[1:]:
            name, _, raw = part.partition("=")
            if name == "avg10":
                try:
                    figures[parts[0]] = float(raw)
                except ValueError:
                    return None
    if "some" not in figures or "full" not in figures:
        return None
    if figures["full"] >= 5:
        return MEM_CRITICAL
    return MEM_WARN if figures["some"] >= 10 else MEM_NORMAL


def read_mem_pressure(system: str) -> Optional[str]:
    if system == "Darwin":
        return _DARWIN_LEVELS.get(_darwin_level() or 0)
    if system == "Linux":
        try:
            with open(_PSI_PATH, encoding="ascii") as handle:
                return parse_psi(handle.read())
        except OSError:
            return None
    return None


def read_run_queue(cores: int, system: str = "Linux") -> Optional[float]:
    if not cores or cores < 1 or system == "Darwin":
        return None
    try:
        return os.getloadavg()[0] / cores
    except (OSError, AttributeError):
        return None


class Gauge:

    def __init__(self, measure: Callable[[], Optional[Tuple[float, float, int]]], mem: Callable[[], Optional[str]],
                 run_queue: Callable[[], Optional[float]], throttled: Callable[[], int], holds: holds_mod.Holds,
                 clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time) -> None:
        self._measure, self._mem, self._rq, self._throttled, self._holds = measure, mem, run_queue, throttled, holds
        self._clock, self._wall = clock, wall
        self._lock = threading.Lock()
        self._pegged = False
        self._since: Optional[float] = None
        self._why = ""
        self._under_since: Optional[float] = None
        self._last: Dict[str, Any] = {"busy_cores": None, "line": None, "cores": None, "run_queue_per_core": None, "mem": None}
        self._hours: Dict[int, Dict[str, Any]] = {}

    def tick(self) -> None:
        figures, mem, rq = self._measure(), self._mem(), self._rq()
        busy = line = cores = None
        if figures is not None:
            busy, line, cores = figures
        reasons: List[str] = []
        if busy is not None and busy > line:
            reasons.append(f"busy cores {busy:.1f} over the reserve line {line:.1f}")
        if rq is not None and rq > RUN_QUEUE_ON:
            reasons.append(f"run queue {rq:.1f} per core")
        if mem in (MEM_WARN, MEM_CRITICAL):
            reasons.append(f"memory pressure {mem}")
        calm = ((busy is None or busy < line - CLEAR_MARGIN * cores) and (rq is None or rq < RUN_QUEUE_OFF)
                and (mem is None or mem == MEM_NORMAL))
        now = self._clock()
        with self._lock:
            self._last = {"busy_cores": busy, "line": line, "cores": cores, "run_queue_per_core": rq, "mem": mem}
            if reasons:
                if not self._pegged:
                    self._since = self._wall()
                self._pegged, self._why, self._under_since = True, "; ".join(reasons), None
            elif self._pegged:
                if calm:
                    self._under_since = now if self._under_since is None else self._under_since
                    if now - self._under_since >= CLEAR_AFTER_SECONDS:
                        self._pegged, self._why, self._since, self._under_since = False, "", None, None
                else:
                    self._under_since = None
            self._book(busy, cores, rq, mem)

    def _book(self, busy: Optional[float], cores: Optional[int], rq: Optional[float], mem: Optional[str]) -> None:
        row = self._hours.setdefault(int(self._wall() // 3600), {"ticks": 0, "busy_sum": 0.0, "busy_n": 0, "pegged_ticks": 0,
                                                              "rq_max": None, "mem_ticks": 0})
        row["ticks"] += 1
        if busy is not None and cores:
            row["busy_sum"] += busy / cores
            row["busy_n"] += 1
        row["pegged_ticks"] += 1 if self._pegged else 0
        row["mem_ticks"] += 1 if mem in (MEM_WARN, MEM_CRITICAL) else 0
        if rq is not None:
            row["rq_max"] = rq if row["rq_max"] is None else max(row["rq_max"], rq)
        for stale in sorted(self._hours)[:-_HOURS_KEPT]:
            del self._hours[stale]

    def pegged(self) -> bool:
        with self._lock:
            return self._pegged

    def view(self) -> Dict[str, Any]:
        cpu, ram, count = self._holds.total()
        with self._lock:
            return {"pegged": self._pegged, "since": self._since, "why": self._why, **self._last,
                    "held": {"cpu": cpu, "ram_gb": ram, "n": count}, "throttled": self._throttled()}

    def hours(self) -> List[Dict[str, Any]]:
        with self._lock:
            current = int(self._wall() // 3600)
            out = [{"hour": h, "busy_pct": round(100 * r["busy_sum"] / r["busy_n"], 1) if r["busy_n"] else None,
                    "pegged_minutes": round(r["pegged_ticks"] * 10 / 60, 1), "max_run_queue_per_core": r["rq_max"],
                    "mem_warn_minutes": round(r["mem_ticks"] * 10 / 60, 1)} for h, r in sorted(self._hours.items())]
            for hour in [h for h in self._hours if h != current]:
                del self._hours[hour]
            return out
