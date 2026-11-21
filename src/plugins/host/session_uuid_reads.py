
from __future__ import annotations

import sqlite3
from typing import Callable, Dict, List

import structlog

from src.core.db_reuse.change_cache import ChangeCache, main_file
from src.core.db_reuse.kept_read import forget_kept, kept_connection

logger = structlog.get_logger()

_UUID_READS = ChangeCache()


def session_uuids(row_ids: List[int]) -> Dict[int, str]:
    if not row_ids:
        return {}
    from src.api.peer_auth import open_db  # noqa: PLC0415

    try:
        every = _UUID_READS.fetch_opened(open_db, "session_uuids", lambda: _read_session_uuids(open_db))
    except sqlite3.Error as exc:
        logger.warning("cplug_session_uuids_unreadable", error_type=type(exc).__name__, error=str(exc))
        return {}
    return {rid: every[rid] for rid in row_ids if rid in every}


def _read_session_uuids(open_db: Callable[[], sqlite3.Connection]) -> tuple:
    with kept_connection(open_db) as conn:
        try:
            rows = conn.execute("SELECT id, session_uuid FROM sessions").fetchall()
            return {int(r[0]): str(r[1]) for r in rows if r[1]}, main_file(conn)
        except sqlite3.Error as exc:
            forget_kept(open_db, exc)
            raise
