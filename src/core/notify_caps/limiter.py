
from __future__ import annotations

import time
from collections import deque
from typing import Callable, Deque, Dict

MISS_LIMIT = 10
WINDOW_SECONDS = 600.0
MAX_ADDRESSES = 4096


class MissLimiter:

    def __init__(self, *, limit: int = MISS_LIMIT, window: float = WINDOW_SECONDS,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._limit, self._window, self._clock = limit, window, clock
        self._misses: Dict[str, Deque[float]] = {}

    def _live(self, address: str) -> Deque[float]:
        queue = self._misses.setdefault(address, deque())
        cutoff = self._clock() - self._window
        while queue and queue[0] <= cutoff:
            queue.popleft()
        if not queue:
            self._misses.pop(address, None)
        return queue

    def blocked(self, address: str) -> bool:
        return len(self._live(address)) >= self._limit

    def miss(self, address: str) -> None:
        if len(self._misses) >= MAX_ADDRESSES and address not in self._misses:
            for stale in list(self._misses)[: MAX_ADDRESSES // 8]:
                self._misses.pop(stale, None)
        self._misses.setdefault(address, deque()).append(self._clock())


LIMITER = MissLimiter()
