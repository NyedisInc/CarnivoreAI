
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Set, Tuple

import structlog

from src.core.db_models import (
    DEFAULT_TMUX_SOCKET,
    SESSION_ORIGIN_CREATED,
    SESSION_ORIGIN_OBSERVED,
)
from src.core.session_store import sessions_table_ready
from src.core.hosts.ddl import LOCAL_HOST_KEY, host_scope

logger = structlog.get_logger()

PROMOTE_APPLIED = "applied"
PROMOTE_NOT_ELIGIBLE = "not_eligible"
PROMOTE_NO_ROW = "no_row"
PROMOTE_NO_TABLE = "no_table"


def _eligible_clause() -> str:
    return "origin = ? AND user_declined_at IS NULL"


def _row_exists(
    conn: sqlite3.Connection, socket: str, name: str, epoch: Optional[int], *,
    host_key: str = LOCAL_HOST_KEY,
) -> bool:
    if epoch is None:
        return False
    scope_sql, scope_params = host_scope(conn, host_key)
    row = conn.execute(
        f"SELECT 1 FROM sessions WHERE tmux_socket = ?{scope_sql} AND tmux_name = ? "
        "AND tmux_created_epoch = ?",
        (socket, *scope_params, name, int(epoch)),
    ).fetchone()
    return row is not None


def promote_to_created(
    conn: sqlite3.Connection,
    *,
    socket: str = DEFAULT_TMUX_SOCKET,
    name: str,
    epoch: Optional[int],
    now: str,
    lifecycle_source: Optional[str] = None,
    host_key: str = LOCAL_HOST_KEY,
) -> str:
    if not sessions_table_ready(conn):
        return PROMOTE_NO_TABLE
    if not _row_exists(conn, socket, name, epoch, host_key=host_key):
        return PROMOTE_NO_ROW
    scope_sql, scope_params = host_scope(conn, host_key)
    cur = conn.execute(
        "UPDATE sessions SET origin = ?, lifecycle_source = COALESCE(?, "
        "lifecycle_source), updated_at = ? "
        f"WHERE tmux_socket = ?{scope_sql} AND tmux_name = ? AND tmux_created_epoch = ? "
        f"AND {_eligible_clause()}",
        (
            SESSION_ORIGIN_CREATED,
            lifecycle_source,
            now,
            socket,
            *scope_params,
            name,
            int(epoch),
            SESSION_ORIGIN_OBSERVED,
        ),
    )
    if cur.rowcount:
        logger.info(
            "session_import_promoted",
            tmux_name=name,
            epoch=epoch,
            lifecycle_source=lifecycle_source,
        )
        return PROMOTE_APPLIED
    return PROMOTE_NOT_ELIGIBLE


def record_decline(
    conn: sqlite3.Connection,
    *,
    socket: str = DEFAULT_TMUX_SOCKET,
    name: str,
    epoch: Optional[int],
    now: str,
    host_key: str = LOCAL_HOST_KEY,
) -> str:
    if not sessions_table_ready(conn):
        return PROMOTE_NO_TABLE
    if not _row_exists(conn, socket, name, epoch, host_key=host_key):
        return PROMOTE_NO_ROW
    scope_sql, scope_params = host_scope(conn, host_key)
    cur = conn.execute(
        "UPDATE sessions SET user_declined_at = ?, updated_at = ? "
        f"WHERE tmux_socket = ?{scope_sql} AND tmux_name = ? AND tmux_created_epoch = ? "
        f"AND {_eligible_clause()}",
        (now, now, socket, *scope_params, name, int(epoch), SESSION_ORIGIN_OBSERVED),
    )
    if cur.rowcount:
        logger.info("session_import_declined", tmux_name=name, epoch=epoch)
        return PROMOTE_APPLIED
    return PROMOTE_NOT_ELIGIBLE


def attribution_settled_instances(
    conn: sqlite3.Connection, *, socket: str = DEFAULT_TMUX_SOCKET,
    host_key: str = LOCAL_HOST_KEY,
) -> Optional[Set[Tuple[str, int]]]:
    if not sessions_table_ready(conn):
        return None
    scope_sql, scope_params = host_scope(conn, host_key)
    rows = conn.execute(
        "SELECT tmux_name, tmux_created_epoch FROM sessions "
        f"WHERE tmux_socket = ?{scope_sql} "
        "AND tmux_name IS NOT NULL AND tmux_created_epoch IS NOT NULL "
        "AND NOT (origin = ? AND user_declined_at IS NULL)",
        (socket, *scope_params, SESSION_ORIGIN_OBSERVED),
    ).fetchall()
    return {(str(r[0]), int(r[1])) for r in rows}


def reexaminable_instances(
    conn: sqlite3.Connection, *, socket: str = DEFAULT_TMUX_SOCKET,
    host_key: str = LOCAL_HOST_KEY,
) -> Set[Tuple[str, int]]:
    if not sessions_table_ready(conn):
        return set()
    scope_sql, scope_params = host_scope(conn, host_key)
    rows = conn.execute(
        "SELECT tmux_name, tmux_created_epoch FROM sessions "
        f"WHERE tmux_socket = ?{scope_sql} AND {_eligible_clause()} "
        "AND tmux_name IS NOT NULL AND tmux_created_epoch IS NOT NULL",
        (socket, *scope_params, SESSION_ORIGIN_OBSERVED),
    ).fetchall()
    return {(str(r[0]), int(r[1])) for r in rows}


def declined_instances(
    conn: sqlite3.Connection, *, socket: str = DEFAULT_TMUX_SOCKET,
    host_key: str = LOCAL_HOST_KEY,
) -> List[Dict[str, Any]]:
    if not sessions_table_ready(conn):
        return []
    scope_sql, scope_params = host_scope(conn, host_key)
    rows = conn.execute(
        "SELECT tmux_name, tmux_created_epoch, user_declined_at FROM sessions "
        f"WHERE tmux_socket = ?{scope_sql} AND user_declined_at IS NOT NULL",
        (socket, *scope_params),
    ).fetchall()
    return [
        {
            "tmux_name": str(r[0]),
            "tmux_created_epoch": r[1],
            "user_declined_at": r[2],
        }
        for r in rows
    ]
