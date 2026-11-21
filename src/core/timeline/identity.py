
from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional, Tuple

import structlog

log = structlog.get_logger(__name__)

TTL_SECONDS: float = 10.0
MISS_RETRY_SECONDS: float = 2.0
_QUERY = "SELECT claude_session_uuid, session_uuid, lifecycle FROM sessions WHERE claude_session_uuid IS NOT NULL ORDER BY id"
LIFECYCLE_RUNNING: str = "running"


class ConversationIndex:

    def __init__(self, db_path: Callable[[], Path], clock: Callable[[], float] = time.monotonic) -> None:
        self._db_path, self._clock = db_path, clock
        self._map: Dict[str, str] = {}
        self._read_at = float("-inf")
        self._lock = threading.Lock()
        self._generation = 0

    def _reload(self) -> None:
        from src.core.db import DatastoreUnreadableError, connect  # noqa: PLC0415

        with self._lock:
            self._generation += 1
            generation = self._generation
        path = self._db_path()
        if not path.exists():
            return
        try:
            with closing(connect(path, create=False)) as conn:
                found = self._pick(conn.execute(_QUERY))
        except (DatastoreUnreadableError, sqlite3.Error) as exc:
            log.warning("timeline_identity_unreadable", error=type(exc).__name__)
            return
        with self._lock:
            if generation == self._generation:
                self._map = found

    @staticmethod
    def _pick(rows: Iterable[Tuple[str, str, Optional[str]]]) -> Dict[str, str]:
        best: Dict[str, Tuple[bool, str]] = {}
        for conv, session, lifecycle in rows:
            live = lifecycle == LIFECYCLE_RUNNING
            held = best.get(conv)
            if held is None or live or not held[0]:
                best[conv] = (live, session)
        return {conv: session for conv, (_live, session) in best.items()}

    def session_of(self, conv: str) -> Optional[str]:
        now = self._clock()
        with self._lock:
            age = now - self._read_at
            stale = age > TTL_SECONDS or (conv not in self._map and age > MISS_RETRY_SECONDS)
            if stale:
                self._read_at = now
        if stale:
            self._reload()
        with self._lock:
            return self._map.get(conv)

    def clear(self) -> None:
        with self._lock:
            self._generation += 1
            self._map, self._read_at = {}, float("-inf")


def _default_db() -> Path:
    from src.core.bookmarks import rows  # noqa: PLC0415

    return rows.db_path()


CONVERSATIONS = ConversationIndex(_default_db)
