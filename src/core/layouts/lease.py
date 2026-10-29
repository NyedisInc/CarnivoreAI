
from __future__ import annotations

import threading
import time
from typing import Callable, Dict, Set

LEASE_SECONDS = 180.0

MAX_LEASES = 256


class LeaseBook:

    def __init__(self, clock: Callable[[], float] = time.monotonic,
                 lease_seconds: float = LEASE_SECONDS) -> None:
        self._clock = clock
        self.lease_seconds = lease_seconds
        self._renewed: Dict[str, float] = {}
        self._lock = threading.Lock()

    def renew(self, layout_uuid: str) -> None:
        with self._lock:
            self._renewed.pop(layout_uuid, None)
            self._renewed[layout_uuid] = self._clock()
            while len(self._renewed) > MAX_LEASES:
                self._renewed.pop(next(iter(self._renewed)))

    def release(self, layout_uuid: str) -> None:
        with self._lock:
            self._renewed.pop(layout_uuid, None)

    def active(self) -> Set[str]:
        now = self._clock()
        with self._lock:
            expired = [u for u, at in self._renewed.items() if now - at >= self.lease_seconds]
            for uuid in expired:
                del self._renewed[uuid]
            return set(self._renewed)


LEASES = LeaseBook()


SESSION_LEASES = LeaseBook()
