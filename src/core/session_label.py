
from __future__ import annotations

import re
import sqlite3
from typing import Optional

import structlog

from src.core.product_identity import strip_session_prefix
from src.core.trail_entry import utc_now
from src.core.hosts.ddl import LOCAL_HOST_KEY, host_scope

logger = structlog.get_logger()

LABEL_MAX_CHARS: int = 200

APP_TMUX_PREFIX = "cloude_"

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class InvalidLabel(ValueError):
    pass


def validate_label(label: Optional[str]) -> str:
    if label is None:
        raise InvalidLabel("a session label cannot be empty")
    cleaned = label.strip()
    if not cleaned:
        raise InvalidLabel("a session label cannot be empty")
    if len(cleaned) > LABEL_MAX_CHARS:
        raise InvalidLabel(
            f"a session label may be at most {LABEL_MAX_CHARS} characters"
        )
    if _CONTROL_CHARS.search(cleaned):
        raise InvalidLabel(
            "a session label cannot contain control characters such as a "
            "newline or a tab"
        )
    return cleaned


def label_from_tmux_name(tmux_name: Optional[str]) -> Optional[str]:
    if not tmux_name:
        return None
    stem = tmux_name
    remainder = strip_session_prefix(stem)
    if remainder:
        stem = remainder
    return stem.replace("_", " ").strip() or tmux_name


def set_label(
    conn: sqlite3.Connection,
    *,
    session_uuid: str,
    label: str,
    now: Optional[str] = None,
) -> bool:
    cleaned = validate_label(label)
    stamp = now or utc_now()
    cursor = conn.execute(
        "UPDATE sessions SET title = ?, updated_at = ? WHERE session_uuid = ?",
        (cleaned, stamp, session_uuid),
    )
    if cursor.rowcount > 0:
        logger.info(
            "session_label_set",
            session_uuid=session_uuid,
            note="title only; no identity column is in this statement",
        )
        return True
    logger.warning(
        "session_label_no_such_row",
        session_uuid=session_uuid,
        note="no row carries that session_uuid, so nothing was labelled",
    )
    return False


def set_label_for_instance(
    conn: sqlite3.Connection,
    *,
    socket: str,
    name: str,
    epoch: Optional[int],
    label: str,
    now: Optional[str] = None,
    host_key: str = LOCAL_HOST_KEY,
) -> bool:
    cleaned = validate_label(label)
    if epoch is None:
        logger.warning(
            "session_label_no_epoch",
            tmux_socket=socket,
            tmux_name=name,
            note=(
                "no creation epoch, so there is no instance to key on; "
                "nothing written rather than relabelling by name"
            ),
        )
        return False
    stamp = now or utc_now()
    scope_sql, scope_params = host_scope(conn, host_key)
    cursor = conn.execute(
        "UPDATE sessions SET title = ?, updated_at = ? "
        f"WHERE tmux_socket = ?{scope_sql} AND tmux_name = ? AND tmux_created_epoch = ?",
        (cleaned, stamp, socket, *scope_params, name, int(epoch)),
    )
    if cursor.rowcount > 0:
        logger.info(
            "session_label_set_for_instance",
            tmux_socket=socket,
            tmux_name=name,
            tmux_created_epoch=int(epoch),
            note="title only; no identity column is in the SET clause",
        )
        return True
    logger.warning(
        "session_label_no_such_instance",
        tmux_socket=socket,
        tmux_name=name,
        tmux_created_epoch=int(epoch),
        note="no row carries that instance triple, so nothing was labelled",
    )
    return False


def _clean_title(value) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def label_for_instance(
    conn: sqlite3.Connection,
    *,
    socket: str,
    name: str,
    epoch: Optional[int],
    host_key: str = LOCAL_HOST_KEY,
) -> Optional[str]:
    if not name or epoch is None:
        return None
    try:
        scope_sql, scope_params = host_scope(conn, host_key)
        row = conn.execute(
            "SELECT title FROM sessions "
            f"WHERE tmux_socket = ?{scope_sql} AND tmux_name = ? AND tmux_created_epoch = ? "
            "ORDER BY id DESC LIMIT 1",
            (socket, *scope_params, name, int(epoch)),
        ).fetchone()
    except (sqlite3.Error, TypeError, ValueError) as exc:
        logger.debug("session_label_instance_read_threw", error=str(exc))
        return None
    if row is None:
        return None
    return _clean_title(dict(row).get("title"))


def label_for_name(
    conn: sqlite3.Connection, *, socket: str, name: str, host_key: str = LOCAL_HOST_KEY
) -> Optional[str]:
    if not name:
        return None
    try:
        scope_sql, scope_params = host_scope(conn, host_key)
        row = conn.execute(
            "SELECT title FROM sessions "
            f"WHERE tmux_socket = ?{scope_sql} AND tmux_name = ? "
            "AND tmux_created_epoch IS NOT NULL "
            "ORDER BY tmux_created_epoch DESC, id DESC LIMIT 1",
            (socket, *scope_params, name),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.debug("session_label_name_read_threw", error=str(exc))
        return None
    if row is None:
        return None
    return _clean_title(dict(row).get("title"))
