"""
A share crate is redacted, so it must never be resumed in place: its sessions are asleep rows whose conversation file is the share's
copy, and the first wake resumes it as a FORK (``--fork-session``), which gives the pane its own new conversation id. The marker is a
``meta`` row ``fork_next_wake:<session_uuid>`` whose value is the ``claude_session_uuid`` it was written for. While the row still
carries that id a wake forks; once the id has changed (the fork was correlated and stored) the marker is stale, so it is deleted and
the session wakes normally. No ``fork_kind`` is overloaded and nothing needs a second table.
"""

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
    """Whether the next wake of ``session_uuid`` must fork; a stale marker is deleted on the way (caller commits).

    Inputs: conn (a write connection); session_uuid; claude_session_uuid (the row's conversation id now).
    Output: bool - True while the marker's conversation is still the row's. Example: wake_forks(conn, "u1", "conv-1") -> True
    """
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
