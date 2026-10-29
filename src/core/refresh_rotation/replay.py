
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

MAX_REMEMBERED_ROTATIONS = 256


@dataclass(frozen=True)
class RotatedPair:

    access_token: str
    refresh_token: str
    refresh_jti: str
    access_expires_at: float


class RotationReplayCache:

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_entries: int = MAX_REMEMBERED_ROTATIONS,
    ) -> None:
        self._clock = clock
        self._max_entries = max_entries
        self._entries: Dict[str, Tuple[float, RotatedPair]] = {}

    def remember(self, old_jti: str, pair: RotatedPair, *, ttl_seconds: float) -> None:
        if ttl_seconds <= 0:
            return
        now = self._clock()
        self._prune(now)
        if len(self._entries) >= self._max_entries:
            self._entries.pop(next(iter(self._entries)))
        self._entries[old_jti] = (now + ttl_seconds, pair)

    def recall(self, old_jti: str) -> Optional[RotatedPair]:
        now = self._clock()
        self._prune(now)
        entry = self._entries.get(old_jti)
        return entry[1] if entry is not None else None

    def _prune(self, now: float) -> None:
        expired = [jti for jti, (deadline, _) in self._entries.items() if deadline <= now]
        for jti in expired:
            del self._entries[jti]
