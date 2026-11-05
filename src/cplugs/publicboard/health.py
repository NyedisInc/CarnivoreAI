
from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional

import structlog

from src.cplugs.publicboard.capability import ForwardedReport

logger = structlog.get_logger()
LOG_EVERY_S = 60.0
MESSAGE = "the proxy is not forwarding the visitor address"


class ProxyHealth:

    def __init__(self, clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time) -> None:
        self._clock, self._wall = clock, wall
        self.missing_count = 0
        self.last_missing_at: Optional[float] = None
        self.last_forwarded_at: Optional[float] = None
        self._last_logged: Optional[float] = None

    def forwarded(self) -> None:
        self.last_forwarded_at = self._wall()

    def missing(self, report: ForwardedReport) -> None:
        self.missing_count += 1
        self.last_missing_at = self._wall()
        now = self._clock()
        if self._last_logged is None or now - self._last_logged >= LOG_EVERY_S:
            self._last_logged = now
            logger.warning("publicboard_no_forwarded_address", peer=report.peer, header_present=report.present, copies=report.copies,
                           shape=report.shape, count=self.missing_count)

    def snapshot(self) -> Dict[str, Any]:
        ok = self.last_missing_at is None or (self.last_forwarded_at is not None and self.last_forwarded_at > self.last_missing_at)
        return {"forwarding_ok": ok, "message": "" if ok else MESSAGE, "missing_count": self.missing_count, "last_missing_at": self.last_missing_at}


HEALTH = ProxyHealth()
