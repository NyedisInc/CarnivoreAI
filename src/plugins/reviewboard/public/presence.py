
from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

TTL_S = 16.0
BEAT_S = 10
MAX_ENTRIES = 2000
MAX_PER_LINK = 20

Who = Tuple[str, str]


class Presence:

    def __init__(self, ttl_s: float = TTL_S, limit: int = MAX_ENTRIES, per_link: int = MAX_PER_LINK) -> None:
        self.per_link = per_link
        self.ttl_s = ttl_s
        self.limit = limit
        self._seen: Dict[str, Dict[Who, float]] = {}

    def touch(self, board: str, who: Who, now: float) -> bool:
        mine = self._seen.setdefault(board, {})
        if who not in mine and sum(1 for held in mine if held[0] == who[0]) >= self.per_link:
            return False
        fresh = who not in mine or now - mine[who] >= self.ttl_s
        mine[who] = now
        if sum(len(v) for v in self._seen.values()) > self.limit:
            self._drop_oldest()
        return fresh

    def present(self, board: str, now: float) -> List[Who]:
        return [who for who, at in self._seen.get(board, {}).items() if now - at < self.ttl_s]

    def expire(self, now: float) -> Set[str]:
        changed: Set[str] = set()
        for board in list(self._seen):
            mine = self._seen[board]
            gone = [who for who, at in mine.items() if now - at >= self.ttl_s]
            for who in gone:
                del mine[who]
            if gone:
                changed.add(board)
            if not mine:
                del self._seen[board]
        return changed

    def next_expiry(self, now: float) -> Optional[float]:
        lasts = [at for mine in self._seen.values() for at in mine.values()]
        return None if not lasts else max(0.0, min(lasts) + self.ttl_s - now)

    def any(self) -> bool:
        return bool(self._seen)

    def _drop_oldest(self) -> None:
        oldest = min(((at, board, who) for board, mine in self._seen.items() for who, at in mine.items()), default=None)
        if oldest is not None:
            _at, board, who = oldest
            del self._seen[board][who]
            if not self._seen[board]:
                del self._seen[board]


PRESENCE = Presence()
