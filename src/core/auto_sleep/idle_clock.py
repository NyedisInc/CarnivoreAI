
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, Iterable, List, Optional, Set

import structlog

from src.core.auto_sleep.idle_seed import SeedResult
from src.core.session_status import STATUS_IDLE

logger = structlog.get_logger()


@dataclass(frozen=True)
class IdleRun:

    key: str
    since: datetime
    last: datetime
    unread: bool = False
    read_since: Optional[datetime] = None


class IdleClock:

    def __init__(self) -> None:
        self._runs: Dict[str, IdleRun] = {}
        self._seeded: Set[str] = set()

    def observe(
        self,
        session_id: str,
        key: str,
        display: str,
        activity_hint: Optional[str],
        observed_at: datetime,
        *,
        seed: Optional[Callable[[], SeedResult]] = None,
        unread: bool = False,
    ) -> None:
        if display != STATUS_IDLE or activity_hint is not None:
            self._runs.pop(session_id, None)
            return
        run = self._runs.get(session_id)
        if run is None or run.key != key or observed_at < run.since:
            since = observed_at
            if session_id not in self._seeded and seed is not None:
                since = self._seed_once(session_id, key, observed_at, seed)
            self._seeded.add(session_id)
            self._runs[session_id] = IdleRun(
                key, since, observed_at, unread, None if unread else observed_at
            )
            return
        if unread:
            read_since = None
        elif run.read_since is None:
            read_since = observed_at
        else:
            read_since = run.read_since
        self._runs[session_id] = IdleRun(
            key, run.since, max(run.last, observed_at), unread, read_since
        )

    def _seed_once(
        self,
        session_id: str,
        key: str,
        observed_at: datetime,
        seed: Callable[[], SeedResult],
    ) -> datetime:
        try:
            result = seed()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "auto_sleep_idle_seed_failed",
                session_id=session_id,
                key=key,
                error_type=type(exc).__name__,
            )
            return observed_at
        idle_seconds = max(0.0, (observed_at - result.since).total_seconds())
        logger.info(
            "auto_sleep_idle_seeded",
            session_id=session_id,
            key=key,
            source=result.source,
            idle_seconds=idle_seconds,
            clamped_to_process_start=result.clamped_to_process_start,
            clamped_to_now=result.clamped_to_now,
        )
        return result.since

    def idle_seconds(self, session_id: str, now: datetime) -> Optional[float]:
        run = self._runs.get(session_id)
        if run is None:
            return None
        return max(0.0, (now - run.since).total_seconds())

    def sleep_seconds(self, session_id: str, now: datetime, *, unread: bool) -> Optional[float]:
        run = self._runs.get(session_id)
        if run is None:
            return None
        start = run.since if unread else (run.read_since or run.since)
        return max(0.0, (now - start).total_seconds())

    def is_unread(self, session_id: str) -> bool:
        run = self._runs.get(session_id)
        return bool(run and run.unread)

    def idle_ids(self) -> List[str]:
        return list(self._runs)

    def run_for(self, session_id: str) -> Optional[IdleRun]:
        return self._runs.get(session_id)

    def forget(self, session_id: str) -> None:
        self._runs.pop(session_id, None)

    def prune(self, live_ids: Iterable[str]) -> None:
        keep = set(live_ids)
        for session_id in [sid for sid in self._runs if sid not in keep]:
            del self._runs[session_id]
