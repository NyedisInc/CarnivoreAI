
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Optional

from src.core.db import connect, get_meta, set_meta

META_PREFIX = "fork_next_wake:"


def marker_key(session_uuid: str) -> str:
    return f"{META_PREFIX}{session_uuid}"


def set_marker(conn: sqlite3.Connection, session_uuid: str, claude_session_uuid: str) -> None:
    set_meta(conn, marker_key(session_uuid), claude_session_uuid)


def wake_forks(conn: sqlite3.Connection, session_uuid: str, claude_session_uuid: Optional[str]) -> bool:
    written_for = get_meta(conn, marker_key(session_uuid))
    if written_for is None:
        return False
    if claude_session_uuid is not None and written_for == claude_session_uuid:
        return True
    conn.execute("DELETE FROM meta WHERE key = ?", (marker_key(session_uuid),))
    return False


def wake_forks_at(db_path: Path, session_uuid: str, claude_session_uuid: Optional[str]) -> bool:
    with closing(connect(db_path, create=False)) as conn:
        forks = wake_forks(conn, session_uuid, claude_session_uuid)
        conn.commit()
        return forks
