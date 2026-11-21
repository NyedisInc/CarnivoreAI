
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple

import structlog

logger = structlog.get_logger()

MIN_DEATHS: int = 3
WINDOW_SECONDS: float = 10.0


@dataclass(frozen=True)
class MassDeathEvent:

    count: int
    session_uuids: Tuple[str, ...]
    at: float


class MassDeathDetector:

    def __init__(self, *, min_deaths: int = MIN_DEATHS, window_s: float = WINDOW_SECONDS) -> None:
        self._min = min_deaths
        self._window = window_s
        self._seen: Dict[str, float] = {}
        self._reported: int = 0
        self._lock = threading.Lock()
        self.last_event: Optional[MassDeathEvent] = None

    def record(self, session_uuids: Sequence[str], now: float) -> Optional[MassDeathEvent]:
        with self._lock:
            self._seen = {u: t for u, t in self._seen.items() if now - t <= self._window}
            for uuid in session_uuids:
                self._seen.setdefault(uuid, now)
            if not self._seen:
                self._reported = 0
            if len(self._seen) < self._min or len(self._seen) <= self._reported:
                return None
            self._reported = len(self._seen)
            self.last_event = MassDeathEvent(count=len(self._seen), session_uuids=tuple(self._seen), at=now)
            return self.last_event


DETECTOR = MassDeathDetector()


def observe(session_uuids: Sequence[str], now: Optional[float] = None) -> Optional[MassDeathEvent]:
    from src.core.mass_death import notice

    event = DETECTOR.record(session_uuids, time.time() if now is None else now)
    if event is None:
        return None
    logger.warning("mass_pane_death_detected", count=event.count, at=event.at, session_uuids=list(event.session_uuids))
    notice.raise_for(event)
    return event
