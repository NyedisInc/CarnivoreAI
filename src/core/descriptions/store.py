
from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import closing
from typing import Any, Dict, Optional

import structlog

from src.core.db import DatastoreUnreadableError, connect, db_path_for, transaction
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

RELOAD_AFTER_SECONDS = 60.0


class DescriptionError(Exception):
    pass


class DescriptionInvalid(DescriptionError):
    pass


class SessionDescriptionNotFound(DescriptionError):
    pass


def clean_text(value: Optional[str], *, single_line: bool) -> Optional[str]:
    if value is None:
        return None
    text = value.strip().replace("\r\n", "\n").replace("\r", "\n")
    if single_line and "\n" in text:
        raise DescriptionInvalid("a short description is one line")
    if any((ord(c) < 32 and c not in ("\t", "\n")) or ord(c) == 127 for c in text):
        raise DescriptionInvalid("a description may not carry a control character")
    return text


def set_session_descriptions(
    conn: sqlite3.Connection,
    session_uuid: str,
    *,
    short_description: Optional[str] = None,
    long_description: Optional[str] = None,
    now: Optional[str] = None,
) -> Dict[str, Any]:
    stamp = now or utc_now()
    with transaction(conn):
        row = conn.execute("SELECT id FROM sessions WHERE session_uuid = ?", (session_uuid,)).fetchone()
        if row is None:
            raise SessionDescriptionNotFound(f"no session row {session_uuid}")
        for column, value in (("short_description", short_description), ("long_description", long_description)):
            if value is not None:
                conn.execute(f"UPDATE sessions SET {column} = ?, updated_at = ? WHERE id = ?",
                             (value or None, stamp, row[0]))
    out = conn.execute("SELECT id, short_description, long_description FROM sessions WHERE id = ?",
                       (row[0],)).fetchone()
    _INDEX.put(int(out[0]), out[1])
    logger.info("session_description_set", session_uuid=session_uuid, short=short_description is not None,
                long=long_description is not None)
    return {"session_uuid": session_uuid, "session_row_id": int(out[0]), "short_description": out[1],
            "long_description": out[2]}


class _ShortIndex:

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: Dict[int, str] = {}
        self._loaded = False
        self._failed_at: Optional[float] = None

    def _load(self, state_dir: Any) -> None:
        try:
            with closing(connect(db_path_for(state_dir), create=False)) as conn:
                rows = {int(r[0]): r[1] for r in conn.execute(
                    "SELECT id, short_description FROM sessions WHERE short_description IS NOT NULL")}
        except (DatastoreUnreadableError, sqlite3.Error) as exc:
            logger.warning("session_description_index_load_failed", error=type(exc).__name__)
            self._failed_at = time.monotonic()
            return
        self._rows, self._loaded, self._failed_at = rows, True, None

    def get(self, row_id: Optional[int], state_dir: Any) -> Optional[str]:
        if row_id is None:
            return None
        with self._lock:
            if not self._loaded and (self._failed_at is None
                                     or time.monotonic() - self._failed_at >= RELOAD_AFTER_SECONDS):
                self._load(state_dir)
            return self._rows.get(int(row_id))

    def put(self, row_id: int, short: Optional[str]) -> None:
        with self._lock:
            if short:
                self._rows[row_id] = short
            else:
                self._rows.pop(row_id, None)

    def reset(self) -> None:
        with self._lock:
            self._rows, self._loaded, self._failed_at = {}, False, None


_INDEX = _ShortIndex()


def short_for_row(row_id: Optional[int], state_dir: Any) -> Optional[str]:
    return _INDEX.get(row_id, state_dir)


def reset_index() -> None:
    _INDEX.reset()
