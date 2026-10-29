
from __future__ import annotations

import sqlite3
from typing import Dict, List, Optional, Sequence, Tuple

from src.core.db import table_exists, transaction
from src.core.session_group_errors import (
    GroupNotFound,
    GroupsUnavailable,
    SessionGroupError,
    SessionNotStored,
)
from src.core.session_group_membership_migrate import resolve_session_uuid
from src.core.trail_entry import utc_now

REQUIRED_TABLES: Tuple[str, ...] = ("session_groups", "session_group_membership")

LAYOUT_MEMBER_PREFIX = "layout:"


def layout_member_key(layout_uuid: str) -> str:
    return f"{LAYOUT_MEMBER_PREFIX}{layout_uuid}"


def require_tables(conn: sqlite3.Connection) -> None:
    for table in REQUIRED_TABLES:
        if not table_exists(conn, table):
            raise GroupsUnavailable(
                f"table {table!r} is not present in this datastore"
            )


def group_id_for(conn: sqlite3.Connection, group_uuid: str) -> int:
    row = conn.execute(
        "SELECT id FROM session_groups WHERE group_uuid = ?", (group_uuid,)
    ).fetchone()
    if row is None:
        raise GroupNotFound(f"no group with uuid {group_uuid!r}")
    return int(row[0])


def session_uuid_for_name(conn: sqlite3.Connection, tmux_name: str) -> str:
    if not isinstance(tmux_name, str) or not tmux_name.strip():
        raise SessionGroupError("tmux_name is empty")
    if not table_exists(conn, "sessions"):
        raise SessionNotStored(
            "this datastore has no sessions table, so a tmux name cannot "
            "be resolved to a durable session identity"
        )
    resolved = resolve_session_uuid(conn, tmux_name)
    if resolved is None:
        raise SessionNotStored(
            f"no sessions row carries the tmux name {tmux_name!r}, so there "
            "is no durable identity to file it under"
        )
    return resolved


def members_by_group(
    conn: sqlite3.Connection,
) -> Dict[int, List[Tuple[str, Optional[str]]]]:
    out: Dict[int, List[Tuple[str, Optional[str]]]] = {}
    rows = conn.execute(
        "SELECT m.group_id, m.session_uuid, s.tmux_name "
        "FROM session_group_membership m "
        "LEFT JOIN sessions s ON s.session_uuid = m.session_uuid "
        "ORDER BY m.group_id ASC, m.position ASC, m.session_uuid ASC"
    ).fetchall()
    for row in rows:
        name = None if row[2] is None else str(row[2])
        out.setdefault(int(row[0]), []).append((str(row[1]), name))
    return out


def assign_session(
    conn: sqlite3.Connection,
    session_uuid: str,
    group_uuid: Optional[str],
    *,
    now: Optional[str] = None,
) -> None:
    require_tables(conn)
    if not isinstance(session_uuid, str) or not session_uuid.strip():
        raise SessionGroupError("session_uuid is empty")
    with transaction(conn):
        if group_uuid is None:
            conn.execute(
                "DELETE FROM session_group_membership WHERE session_uuid = ?",
                (session_uuid,),
            )
            return
        gid = group_id_for(conn, group_uuid)
        tail = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 "
            "FROM session_group_membership WHERE group_id = ?",
            (gid,),
        ).fetchone()[0]
        conn.execute(
            "DELETE FROM session_group_membership WHERE session_uuid = ?",
            (session_uuid,),
        )
        conn.execute(
            "INSERT INTO session_group_membership "
            "(session_uuid, group_id, position, added_at) VALUES (?, ?, ?, ?)",
            (session_uuid, gid, int(tail), now or utc_now()),
        )


def assign(
    conn: sqlite3.Connection,
    tmux_name: str,
    group_uuid: Optional[str],
    *,
    now: Optional[str] = None,
) -> None:
    require_tables(conn)
    assign_session(
        conn, session_uuid_for_name(conn, tmux_name), group_uuid, now=now
    )


def assign_layout(
    conn: sqlite3.Connection,
    layout_uuid: str,
    group_uuid: Optional[str],
    *,
    now: Optional[str] = None,
) -> None:
    require_tables(conn)
    if not isinstance(layout_uuid, str) or not layout_uuid.strip():
        raise SessionGroupError("layout_uuid is empty")
    assign_session(conn, layout_member_key(layout_uuid), group_uuid, now=now)


def group_of_session(
    conn: sqlite3.Connection, session_uuid: str
) -> Optional[str]:
    require_tables(conn)
    row = conn.execute(
        "SELECT g.group_uuid FROM session_group_membership m "
        "JOIN session_groups g ON g.id = m.group_id "
        "WHERE m.session_uuid = ?",
        (session_uuid,),
    ).fetchone()
    return str(row[0]) if row is not None else None


def group_of(conn: sqlite3.Connection, tmux_name: str) -> Optional[str]:
    require_tables(conn)
    try:
        session_uuid = session_uuid_for_name(conn, tmux_name)
    except SessionNotStored:
        return None
    return group_of_session(conn, session_uuid)


def set_member_order(
    conn: sqlite3.Connection, group_uuid: str, session_uuids: Sequence[str]
) -> None:
    require_tables(conn)
    with transaction(conn):
        gid = group_id_for(conn, group_uuid)
        current = [
            str(r[0])
            for r in conn.execute(
                "SELECT session_uuid FROM session_group_membership "
                "WHERE group_id = ? ORDER BY position ASC, session_uuid ASC",
                (gid,),
            )
        ]
        known = set(current)
        seen: List[str] = []
        for session_uuid in session_uuids:
            if session_uuid in known and session_uuid not in seen:
                seen.append(session_uuid)
        rest = [u for u in current if u not in seen]
        for index, session_uuid in enumerate(seen + rest):
            conn.execute(
                "UPDATE session_group_membership SET position = ? "
                "WHERE session_uuid = ?",
                (index, session_uuid),
            )


def clear_group(conn: sqlite3.Connection, group_id: int) -> int:
    freed = int(
        conn.execute(
            "SELECT COUNT(*) FROM session_group_membership WHERE group_id = ?",
            (group_id,),
        ).fetchone()[0]
    )
    conn.execute(
        "DELETE FROM session_group_membership WHERE group_id = ?", (group_id,)
    )
    return freed


def prune_missing(conn: sqlite3.Connection, live_names: Sequence[str]) -> int:
    require_tables(conn)
    if not live_names:
        return 0
    if not table_exists(conn, "sessions"):
        return 0
    keep = set(live_names)
    with transaction(conn):
        doomed = [
            str(r[0])
            for r in conn.execute(
                "SELECT m.session_uuid, s.tmux_name "
                "FROM session_group_membership m "
                "JOIN sessions s ON s.session_uuid = m.session_uuid "
                "WHERE s.tmux_name IS NOT NULL"
            )
            if str(r[1]) not in keep
        ]
        for session_uuid in doomed:
            conn.execute(
                "DELETE FROM session_group_membership WHERE session_uuid = ?",
                (session_uuid,),
            )
    return len(doomed)
