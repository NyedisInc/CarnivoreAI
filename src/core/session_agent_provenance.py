
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional

import structlog

from src.core.db_models import (
    SESSION_FAMILY_SOURCE_FINGERPRINT,
    SESSION_FAMILY_SOURCE_INFERRED_PROCESS,
    SESSION_FAMILY_SOURCE_LAUNCHED,
    SESSION_FAMILY_SOURCE_NOT_LAUNCHED,
)
from src.core.hosts.ddl import LOCAL_HOST_KEY, host_scope

logger = structlog.get_logger()

DEFINITE_LAUNCH_SOURCES = frozenset(
    {SESSION_FAMILY_SOURCE_LAUNCHED, SESSION_FAMILY_SOURCE_NOT_LAUNCHED}
)


@dataclass(frozen=True)
class StoredLaunch:

    known: bool
    agent_type: Optional[str] = None
    from_fingerprint: bool = False
    from_process: bool = False


NOT_KNOWN = StoredLaunch(known=False)


def stored_launch_for(
    conn: sqlite3.Connection,
    *,
    socket: str,
    name: str,
    epoch: Optional[int],
    host_key: str = LOCAL_HOST_KEY,
) -> StoredLaunch:
    if epoch is None:
        return NOT_KNOWN
    try:
        scope_sql, scope_params = host_scope(conn, host_key)
        row = conn.execute(
            "SELECT agent_type, agent_family_source FROM sessions "
            f"WHERE tmux_socket = ?{scope_sql} AND tmux_name = ? "
            "AND tmux_created_epoch = ?",
            (socket, *scope_params, name, int(epoch)),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning(
            "stored_launch_read_failed",
            tmux_socket=socket,
            tmux_name=name,
            error=str(exc),
            note="reported as not-known; nothing is claimed about the agent",
        )
        return NOT_KNOWN
    if row is None:
        return NOT_KNOWN
    data = dict(row)
    source = data.get("agent_family_source")
    if source == SESSION_FAMILY_SOURCE_INFERRED_PROCESS:
        return StoredLaunch(
            known=True,
            agent_type=data.get("agent_type"),
            from_fingerprint=False,
            from_process=True,
        )
    if source not in DEFINITE_LAUNCH_SOURCES:
        return NOT_KNOWN
    return StoredLaunch(
        known=True,
        agent_type=data.get("agent_type"),
        from_fingerprint=False,
    )


def persist_fingerprint_family(
    conn: sqlite3.Connection,
    *,
    session_uuid: str,
    agent_family: str,
) -> bool:
    if not session_uuid or not agent_family:
        return False
    placeholders = ", ".join("?" for _ in DEFINITE_LAUNCH_SOURCES)
    try:
        cursor = conn.execute(
            "UPDATE sessions SET agent_family = ?, agent_family_source = ? "
            "WHERE session_uuid = ? "
            "AND (agent_type IS NULL OR agent_type = '') "
            "AND (agent_family IS NULL OR agent_family = '') "
            f"AND agent_family_source NOT IN ({placeholders})",
            (
                agent_family,
                SESSION_FAMILY_SOURCE_FINGERPRINT,
                session_uuid,
                *DEFINITE_LAUNCH_SOURCES,
            ),
        )
    except sqlite3.Error as exc:
        logger.warning(
            "fingerprint_family_persist_failed",
            session_uuid=session_uuid,
            agent_family=agent_family,
            error=str(exc),
            note="best-effort write; the caller's own operation is unaffected",
        )
        return False
    return cursor.rowcount > 0
