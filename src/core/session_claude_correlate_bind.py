
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional

import structlog

from src.core.db_models import (
    SESSION_CLAUDE_UUID_SOURCE_CORRELATED,
    SESSION_CLAUDE_UUID_SOURCE_HOOK,
    SESSION_CLAUDE_UUID_SOURCE_REGISTRY,
    SESSION_CLAUDE_UUID_SOURCES,
)
from src.core.session_lineage import row_for_claude_uuid
from src.core.session_store import get_instance, sessions_table_ready
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

_NOT_CORRELATED = (
    SESSION_CLAUDE_UUID_SOURCE_HOOK,
    SESSION_CLAUDE_UUID_SOURCE_REGISTRY,
)

BIND_BOUND = "bound"

BIND_REBOUND = "rebound"

BIND_ALREADY_KNOWN = "already_known"

BIND_UNRESOLVED = "unresolved"

BIND_NO_WRITE = (BIND_ALREADY_KNOWN, BIND_UNRESOLVED)


_SAVEPOINT_NAME = "bind_correlated_pair"
_SAVEPOINT_OPEN = f"SAVEPOINT {_SAVEPOINT_NAME}"
_SAVEPOINT_ROLLBACK = f"ROLLBACK TO {_SAVEPOINT_NAME}"
_SAVEPOINT_RELEASE = f"RELEASE {_SAVEPOINT_NAME}"


@dataclass(frozen=True)
class BindResult:

    outcome: str
    row_id: Optional[int] = None
    detail: Optional[str] = None

    took_from_row_id: Optional[int] = None

    @property
    def wrote(self) -> bool:
        return self.outcome not in BIND_NO_WRITE


def _row_to_release(
    conn: sqlite3.Connection,
    *,
    known_row_id: int,
    takes_from_row_id: Optional[int],
    socket: str,
    name: str,
    epoch: Optional[int],
) -> Optional[int]:
    if takes_from_row_id is None:
        return None
    if known_row_id != int(takes_from_row_id):
        return None
    anchor = get_instance(conn, socket=socket, name=name, epoch=epoch)
    if anchor is None or int(anchor["id"]) == known_row_id:
        return None
    return known_row_id


def bind_correlated_uuid(
    conn: sqlite3.Connection,
    *,
    socket: str,
    name: str,
    epoch: Optional[int],
    claude_uuid: str,
    source: str = SESSION_CLAUDE_UUID_SOURCE_CORRELATED,
    replaces_uuid: Optional[str] = None,
    takes_from_row_id: Optional[int] = None,
    now: Optional[str] = None,
) -> BindResult:
    stamp = now or utc_now()

    if not sessions_table_ready(conn):
        return BindResult(
            outcome=BIND_UNRESOLVED,
            detail="the datastore has no sessions table (pre-v2)",
        )
    if not claude_uuid:
        return BindResult(
            outcome=BIND_UNRESOLVED,
            detail="no claude_session_uuid was resolved to bind",
        )

    known = row_for_claude_uuid(conn, claude_uuid)
    release_from: Optional[int] = None
    if known is not None:
        release_from = _row_to_release(
            conn,
            known_row_id=int(known["id"]),
            takes_from_row_id=takes_from_row_id,
            socket=socket,
            name=name,
            epoch=epoch,
        )
        if release_from is None:
            return BindResult(
                outcome=BIND_ALREADY_KNOWN,
                row_id=int(known["id"]),
                detail=f"session {claude_uuid} is already recorded",
            )

    anchor = get_instance(conn, socket=socket, name=name, epoch=epoch)
    if anchor is None:
        return BindResult(
            outcome=BIND_UNRESOLVED,
            detail=(
                "no sessions row carries this tmux instance triple "
                f"({socket}/{name}/{epoch})"
            ),
        )

    incumbent = anchor.get("claude_session_uuid")
    replacing = bool(incumbent) and bool(replaces_uuid) and incumbent == replaces_uuid
    if incumbent and not replacing:
        return BindResult(
            outcome=BIND_UNRESOLVED,
            row_id=int(anchor["id"]),
            detail=(
                "the anchor row already carries a different "
                "claude_session_uuid"
                if not replaces_uuid
                else (
                    "the anchor row carries a claude_session_uuid the "
                    "caller did not measure, so the rebind decision is stale"
                )
            ),
        )

    honest_registry_rebind = (
        replacing or release_from is not None
    ) and source == SESSION_CLAUDE_UUID_SOURCE_REGISTRY
    if not honest_registry_rebind and (
        source not in SESSION_CLAUDE_UUID_SOURCES or source in _NOT_CORRELATED
    ):
        logger.warning(
            "claude_uuid_correlate_bind_unknown_source",
            requested_source=source,
            note="not a recognised correlated provenance; downgraded to the "
            "timing default rather than written verbatim",
        )
        source = SESSION_CLAUDE_UUID_SOURCE_CORRELATED

    if release_from is not None:
        conn.execute(_SAVEPOINT_OPEN)
    try:
        if release_from is not None:
            conn.execute(
                "UPDATE sessions SET claude_session_uuid = NULL, "
                "claude_session_uuid_source = NULL, updated_at = ? "
                "WHERE id = ? AND claude_session_uuid = ?",
                (stamp, int(release_from), claude_uuid),
            )
        conn.execute(
            "UPDATE sessions SET claude_session_uuid = ?, "
            "claude_session_uuid_source = ?, updated_at = ? WHERE id = ?",
            (
                claude_uuid,
                source,
                stamp,
                int(anchor["id"]),
            ),
        )
        if release_from is not None:
            conn.execute(_SAVEPOINT_RELEASE)
    except sqlite3.IntegrityError as exc:
        if release_from is not None:
            conn.execute(_SAVEPOINT_ROLLBACK)
            conn.execute(_SAVEPOINT_RELEASE)
        logger.warning(
            "claude_uuid_correlate_bind_race",
            row_id=int(anchor["id"]),
            claude_session_uuid=claude_uuid,
            error=str(exc),
        )
        return BindResult(
            outcome=BIND_UNRESOLVED,
            row_id=int(anchor["id"]),
            detail=f"unique constraint raced this write: {exc}",
        )

    logger.info(
        "claude_uuid_rebound" if replacing else "claude_uuid_correlated",
        row_id=int(anchor["id"]),
        tmux_name=name,
        claude_session_uuid=claude_uuid,
        replaced_claude_session_uuid=replaces_uuid if replacing else None,
        released_from_row_id=release_from,
        source=source,
    )
    return BindResult(
        outcome=BIND_REBOUND if replacing else BIND_BOUND,
        row_id=int(anchor["id"]),
        took_from_row_id=release_from,
    )
