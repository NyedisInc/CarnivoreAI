
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

MEMBERSHIP_CARRIED = "carried"

MEMBERSHIP_UNRESOLVED = "unresolved"

MEMBERSHIP_ALREADY_PRESENT = "already_present"


@dataclass(frozen=True)
class CarriedMembership:

    tmux_name: str
    group_id: int
    session_uuid: Optional[str]
    position: Optional[int]
    outcome: str


def resolve_session_uuid(
    conn: sqlite3.Connection, tmux_name: str, host_key: str = "local"
) -> Optional[str]:
    from src.core.hosts.ddl import host_scope

    scope_sql, scope_params = host_scope(conn, host_key)
    row = conn.execute(
        f"SELECT session_uuid FROM sessions WHERE tmux_name = ?{scope_sql} "
        "ORDER BY (lifecycle = 'running') DESC, id DESC LIMIT 1",
        (tmux_name, *scope_params),
    ).fetchone()
    return None if row is None else str(row[0])


def _legacy_rows(conn: sqlite3.Connection) -> List[Tuple[str, int, str]]:
    return [
        (str(r[0]), int(r[1]), str(r[2]))
        for r in conn.execute(
            "SELECT tmux_name, group_id, added_at FROM session_group_members "
            "ORDER BY added_at ASC, tmux_name ASC"
        )
    ]


def carry_memberships(conn: sqlite3.Connection) -> List[CarriedMembership]:
    held = {
        str(r[0])
        for r in conn.execute("SELECT session_uuid FROM session_group_membership")
    }
    next_position: Dict[int, int] = {}
    for row in conn.execute(
        "SELECT group_id, COALESCE(MAX(position), -1) + 1 "
        "FROM session_group_membership GROUP BY group_id"
    ):
        next_position[int(row[0])] = int(row[1])

    out: List[CarriedMembership] = []
    for tmux_name, group_id, added_at in _legacy_rows(conn):
        session_uuid = resolve_session_uuid(conn, tmux_name)
        if session_uuid is None:
            out.append(
                CarriedMembership(
                    tmux_name, group_id, None, None, MEMBERSHIP_UNRESOLVED
                )
            )
            continue
        if session_uuid in held:
            out.append(
                CarriedMembership(
                    tmux_name,
                    group_id,
                    session_uuid,
                    None,
                    MEMBERSHIP_ALREADY_PRESENT,
                )
            )
            continue
        position = next_position.get(group_id, 0)
        next_position[group_id] = position + 1
        conn.execute(
            "INSERT INTO session_group_membership "
            "(session_uuid, group_id, position, added_at) VALUES (?, ?, ?, ?)",
            (session_uuid, group_id, position, added_at),
        )
        held.add(session_uuid)
        out.append(
            CarriedMembership(
                tmux_name, group_id, session_uuid, position, MEMBERSHIP_CARRIED
            )
        )
    return out
