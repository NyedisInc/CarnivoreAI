
from __future__ import annotations

import threading
import time
from typing import Callable, Dict, Optional

from src.api.size_master import valid_client_id

LEASE_SECONDS = 60.0
MAX_LEASES = 64


class PresenceLeases:

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._leases: Dict[str, float] = {}
        self._lock = threading.Lock()

    def beacon(self, client_id: str, active: bool) -> bool:
        if not valid_client_id(client_id):
            return False
        with self._lock:
            self._leases.pop(client_id, None)
            if active:
                self._prune()
                while len(self._leases) >= MAX_LEASES:
                    self._leases.pop(next(iter(self._leases)))
                self._leases[client_id] = self._clock() + LEASE_SECONDS
        return True

    def is_screen_active(self, now: Optional[float] = None) -> bool:
        with self._lock:
            self._prune(now)
            return bool(self._leases)

    def _prune(self, now: Optional[float] = None) -> None:
        now = self._clock() if now is None else now
        for key in [k for k, exp in self._leases.items() if exp <= now]:
            del self._leases[key]


presence = PresenceLeases()
