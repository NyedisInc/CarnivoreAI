
from __future__ import annotations

import time
from typing import Dict, Tuple

import structlog

logger = structlog.get_logger()

MISS_BACKOFF_SECONDS = 30.0
MISS_BACKOFF_MAX_SECONDS = 120.0


class MissCache:

    def __init__(self, event: str) -> None:
        self.event = event
        self._entries: Dict[str, Tuple[tuple, float, float]] = {}

    def clear(self) -> None:
        self._entries.clear()

    def blocked(self, key: str, stamp: tuple) -> bool:
        entry = self._entries.get(key)
        return entry is not None and entry[0] == stamp and time.monotonic() < entry[1]

    def hit(self, key: str) -> None:
        self._entries.pop(key, None)

    def miss(self, key: str, stamp: tuple) -> None:
        entry = self._entries.get(key)
        backoff = MISS_BACKOFF_SECONDS
        if entry is None:
            logger.info(self.event, key=key)
        elif entry[0] == stamp:
            backoff = min(entry[2] * 2, MISS_BACKOFF_MAX_SECONDS)
        self._entries[key] = (stamp, time.monotonic() + backoff, backoff)
