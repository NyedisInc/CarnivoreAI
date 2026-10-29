
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Iterable, Optional, Tuple

from src.core.session_status_seed import (
    SEED_REFRESH_INTERVAL_SECONDS,
    StatusSeed,
)

_Held = Tuple[StatusSeed, datetime, Optional[int]]


class SessionStatusSeeds:

    def __init__(self) -> None:
        self._seeds: Dict[str, _Held] = {}

    def remember(
        self,
        session_id: str,
        seed: StatusSeed,
        now: Optional[datetime] = None,
        *,
        epoch: Optional[int] = None,
    ) -> StatusSeed:
        stamped = now or datetime.now(timezone.utc)
        self._seeds[session_id] = (seed, stamped, epoch)
        return seed

    def get(self, session_id: str) -> Optional[StatusSeed]:
        held = self._seeds.get(session_id)
        return held[0] if held else None

    def due(
        self,
        session_id: str,
        *,
        now: Optional[datetime] = None,
        interval_seconds: int = SEED_REFRESH_INTERVAL_SECONDS,
        epoch: Optional[int] = None,
    ) -> bool:
        held = self._seeds.get(session_id)
        if held is None:
            return True
        _, stamped, cached_epoch = held
        if cached_epoch is None and epoch is not None:
            return True
        age = (now or datetime.now(timezone.utc)) - stamped
        return age.total_seconds() >= interval_seconds or age.total_seconds() < 0

    def forget(self, session_id: str) -> None:
        self._seeds.pop(session_id, None)

    def prune(self, live_ids: Iterable[str]) -> int:
        keep = set(live_ids or ())
        stale = [sid for sid in self._seeds if sid not in keep]
        for sid in stale:
            self._seeds.pop(sid, None)
        return len(stale)
