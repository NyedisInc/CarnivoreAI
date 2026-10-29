
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Callable, Deque, Dict

PRE_TOTAL = 4
PRE_PER_SOURCE = 2
PER_SOURCE_MINUTE = 5
PER_SOURCE_HOUR = 20
GLOBAL_MINUTE = 20


class Slots:

    def __init__(self, total: int = PRE_TOTAL, per_source: int = PRE_PER_SOURCE) -> None:
        self._total, self._per = total, per_source
        self._by_source: Dict[str, int] = defaultdict(int)
        self._count = 0

    def enter(self, addr: str) -> bool:
        if self._count >= self._total or self._by_source[addr] >= self._per:
            return False
        self._count += 1
        self._by_source[addr] += 1
        return True

    def leave(self, addr: str) -> None:
        self._count = max(0, self._count - 1)
        self._by_source[addr] -= 1
        if self._by_source[addr] <= 0:
            self._by_source.pop(addr, None)


class Rates:

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._src: Dict[str, Deque[float]] = defaultdict(deque)
        self._all: Deque[float] = deque()

    @staticmethod
    def _trim(q: Deque[float], horizon: float) -> None:
        while q and q[0] <= horizon:
            q.popleft()

    def admit(self, addr: str) -> bool:
        now = self._clock()
        src = self._src[addr]
        self._trim(src, now - 3600)
        self._trim(self._all, now - 60)
        if len(src) >= PER_SOURCE_HOUR or len(self._all) >= GLOBAL_MINUTE or sum(1 for x in src if x > now - 60) >= PER_SOURCE_MINUTE:
            return False
        src.append(now)
        self._all.append(now)
        if len(self._src) > 256:
            for key in [k for k, q in self._src.items() if not q or q[-1] <= now - 3600]:
                self._src.pop(key, None)
        return True
