
from __future__ import annotations

import math
import threading
import time
from typing import Callable, Dict, Optional, Set, Tuple

MAX_ENTRIES = 256


class Holds:

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        self._entries: Dict[str, Tuple[str, float, float, float]] = {}
        self._measured: Dict[str, Tuple[float, float]] = {}

    def _expire(self) -> None:
        now = self._clock()
        for key in [k for k, v in self._entries.items() if v[3] <= now]:
            del self._entries[key]
            self._measured.pop(key, None)

    def _total_locked(self, exclude: Optional[str]) -> Tuple[float, float, int]:
        cpu = ram = 0.0
        count = 0
        for k, v in self._entries.items():
            if k == exclude:
                continue
            m_cpu, m_ram = self._measured.get(k, (0.0, 0.0))
            cpu += max(0.0, v[1] - m_cpu)
            ram += max(0.0, v[2] - m_ram)
            count += 1
        return round(cpu, 3), round(ram, 3), count

    def try_hold(self, key: str, owner: str, cpu: float, ram_gb: float, ttl_s: float, fits: Callable[[float, float], bool]) -> bool:
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in (cpu, ram_gb, ttl_s)) or cpu < 0 or ram_gb < 0 or ttl_s <= 0:
            return False
        with self._lock:
            self._expire()
            if key not in self._entries and len(self._entries) >= MAX_ENTRIES:
                return False
            held_cpu, held_ram, _ = self._total_locked(key)
            if not fits(held_cpu, held_ram):
                return False
            self._entries[key] = (owner, float(cpu), float(ram_gb), self._clock() + ttl_s)
            return True

    def extend(self, key: str, ttl_s: float) -> bool:
        with self._lock:
            self._expire()
            entry = self._entries.get(key)
            if entry is None:
                return False
            self._entries[key] = (entry[0], entry[1], entry[2], self._clock() + ttl_s)
            return True

    def set_measured(self, key: str, cpu: float, ram_gb: float) -> bool:
        if not all(isinstance(x, (int, float)) and math.isfinite(x) and x >= 0 for x in (cpu, ram_gb)):
            return False
        with self._lock:
            self._expire()
            if key not in self._entries:
                return False
            self._measured[key] = (float(cpu), float(ram_gb))
            return True

    def drop(self, key: str) -> None:
        with self._lock:
            self._entries.pop(key, None)
            self._measured.pop(key, None)

    def owner(self, key: str) -> Optional[str]:
        with self._lock:
            self._expire()
            entry = self._entries.get(key)
            return entry[0] if entry else None

    def keys_of(self, owner: str) -> Set[str]:
        with self._lock:
            self._expire()
            return {k for k, v in self._entries.items() if v[0] == owner}

    def total(self, exclude: Optional[str] = None) -> Tuple[float, float, int]:
        with self._lock:
            self._expire()
            return self._total_locked(exclude)


HOLDS = Holds()
