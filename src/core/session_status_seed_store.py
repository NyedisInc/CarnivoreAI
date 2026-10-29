
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
        """Whether this session's seed should be re-derived now.

        Description: True for a session never seeded, for one whose seed
          is older than ``interval_seconds``, and - regardless of age -
          for one whose instance epoch was unknown when it was cached and
          is known now. That last rule is what stops a refusal cached as
          "this session's exact tmux instance could not be identified"
          from being permanent: an epoch that arrives late (a boot race
          that resolved it after the first seed attempt) makes the cached
          reading immediately due rather than making it wait out a full
          refresh interval on stale grounds. A clock that appears to run
          backwards (a system time change) also reads due, because
          re-deriving costs one bounded file read and never re-deriving is
          the failure that matters.
        Inputs: session_id (str). now (datetime | None). interval_seconds
          (int) - defaults to :data:`SEED_REFRESH_INTERVAL_SECONDS`.
          epoch (int | None) - the caller's current best epoch for this
          session, or None when it still has none to offer.
        Output: bool.
        Example: seeds.due('s1')
        """
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
