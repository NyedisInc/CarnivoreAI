
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Callable, Tuple

WINDOW_S = 60.0
PER_CLIENT_PER_MIN = 60
PER_LINK_PER_MIN = 120
MAX_KEYS = 4096
LOW_WATER_SHARE = 0.75


def low_water_keys() -> int:
    return max(1, int(MAX_KEYS * LOW_WATER_SHARE))


class RateLimiter:

    def __init__(self, limit: int, clock: Callable[[], float] = time.monotonic) -> None:
        self._limit, self._clock = limit, clock
        self._hits: "OrderedDict[str, Tuple[float, int]]" = OrderedDict()
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            start, count = self._hits.get(key, (now, 0))
            if now - start >= WINDOW_S:
                start, count = now, 0
            self._hits[key] = (start, count + 1)
            self._hits.move_to_end(key)
            if len(self._hits) > MAX_KEYS:
                self._trim(now)
            return count + 1 <= self._limit

    def _trim(self, now: float) -> None:
        for key in [k for k, (start, _) in self._hits.items() if now - start >= WINDOW_S]:
            del self._hits[key]
        while len(self._hits) > low_water_keys():
            self._hits.popitem(last=False)
