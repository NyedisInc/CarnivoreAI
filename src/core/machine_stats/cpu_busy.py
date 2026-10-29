
from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Callable, Deque, Dict, Optional, Tuple

from src.core.swarm.cards import cpu as cards_cpu

SHORT_WINDOW_S = 60.0
LONG_WINDOW_S = 300.0
SAMPLE_GAP_S = 5.0
MIN_SPAN_S = 10.0
SOURCE_TICKS = "cpu_ticks"
SOURCE_LOAD = "load_average"

Ticks = Tuple[int, int]


def read_ticks() -> Optional[Ticks]:
    got = cards_cpu.ticks()
    if got is None:
        return None
    user, system, idle, nice = got
    return user + system + nice, user + system + idle + nice


class CpuMeter:

    def __init__(self, read: Callable[[], Optional[Ticks]] = read_ticks, clock: Callable[[], float] = time.monotonic) -> None:
        self._read, self._clock = read, clock
        self._lock = threading.Lock()
        self._history: Deque[Tuple[float, int, int]] = deque()

    def sample(self) -> Optional[Tuple[float, int, int]]:
        ticks = self._read()
        if ticks is None:
            return None
        now = self._clock()
        point = (now, ticks[0], ticks[1])
        with self._lock:
            if not self._history or now - self._history[-1][0] >= SAMPLE_GAP_S:
                self._history.append(point)
            while self._history and now - self._history[0][0] > 2 * LONG_WINDOW_S:
                self._history.popleft()
        return point

    def busy_fraction(self, window: float) -> Optional[float]:
        latest = self.sample()
        if latest is None:
            return None
        with self._lock:
            older = [p for p in self._history if latest[0] - p[0] >= MIN_SPAN_S]
        if not older:
            return None
        inside = [p for p in older if latest[0] - p[0] <= window]
        base = inside[0] if inside else older[-1]
        if latest[0] - base[0] > 2 * window:
            return None
        busy, total = latest[1] - base[1], latest[2] - base[2]
        if total <= 0 or busy < 0:
            return None
        return min(1.0, busy / total)

    def busy_cores(self, cores: Optional[int] = None) -> Dict[str, object]:
        count = cores or os.cpu_count() or 0
        short, long_ = self.busy_fraction(SHORT_WINDOW_S), self.busy_fraction(LONG_WINDOW_S)
        if not count or short is None:
            return {"busy_1": None, "busy_5": None, "source": SOURCE_LOAD}
        return {"busy_1": round(short * count, 2), "busy_5": round((long_ if long_ is not None else short) * count, 2),
                "source": SOURCE_TICKS}


METER = CpuMeter()
