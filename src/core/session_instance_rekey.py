
from __future__ import annotations

import sqlite3
from typing import Optional

import structlog
from src.core.hosts.ddl import LOCAL_HOST_KEY, host_scope

logger = structlog.get_logger()

IDENTITY_UNCHECKED: str = "unchecked"

IDENTITY_UNCHANGED: str = "unchanged"

IDENTITY_REKEYED: str = "rekeyed"

IDENTITY_CANNOT_DETERMINE: str = "cannot_determine"

ALL_IDENTITY_STATES: frozenset[str] = frozenset(
    {
        IDENTITY_UNCHECKED,
        IDENTITY_UNCHANGED,
        IDENTITY_REKEYED,
        IDENTITY_CANNOT_DETERMINE,
    }
)


def parse_epoch(raw: Optional[str]) -> Optional[int]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or not text.isdigit():
        return None
    return int(text)


def reconcile_instance_epoch(
    conn: Optional[sqlite3.Connection],
    *,
    socket: str,
    tmux_name: str,
    epoch_before: Optional[int],
    epoch_after: Optional[int],
    host_key: str = LOCAL_HOST_KEY,
) -> tuple[str, int]:
    if epoch_before is None or epoch_after is None:
        logger.warning(
            "restart_identity_cannot_determine",
            tmux_name=tmux_name,
            socket=socket,
            epoch_before=epoch_before,
            epoch_after=epoch_after,
        )
        return IDENTITY_CANNOT_DETERMINE, 0

    if epoch_before == epoch_after:
        return IDENTITY_UNCHANGED, 0

    if conn is None:
        logger.error(
            "restart_identity_moved_but_unwritable",
            tmux_name=tmux_name,
            socket=socket,
            epoch_before=epoch_before,
            epoch_after=epoch_after,
        )
        return IDENTITY_CANNOT_DETERMINE, 0

    try:
        scope_sql, scope_params = host_scope(conn, host_key)
        cursor = conn.execute(
            "UPDATE sessions SET tmux_created_epoch = ? "
            f"WHERE tmux_socket = ?{scope_sql} AND tmux_name = ? AND tmux_created_epoch = ?",
            (epoch_after, socket, *scope_params, tmux_name, epoch_before),
        )
        conn.commit()
    except sqlite3.Error as exc:
        logger.error(
            "restart_identity_rekey_failed",
            tmux_name=tmux_name,
            socket=socket,
            error=str(exc),
        )
        return IDENTITY_CANNOT_DETERMINE, 0

    rows = int(cursor.rowcount or 0)
    if rows == 0:
        logger.info(
            "restart_identity_no_row_to_rekey",
            tmux_name=tmux_name,
            socket=socket,
            epoch_before=epoch_before,
            epoch_after=epoch_after,
        )
        return IDENTITY_UNCHANGED, 0

    logger.warning(
        "restart_identity_rekeyed",
        tmux_name=tmux_name,
        socket=socket,
        epoch_before=epoch_before,
        epoch_after=epoch_after,
        rows=rows,
    )
    return IDENTITY_REKEYED, rows
