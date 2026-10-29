
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from weakref import WeakKeyDictionary

import structlog

from src.core.session_status_seed import (
    SEED_RUNG_NONE,
    StatusSeed,
    TranscriptRest,
    display_state,
    resolve_status_seed,
)
from src.core.session_status_seed_store import SessionStatusSeeds
from src.core.session_status_source import (
    STATUS_SOURCE_NONE,
    source_for_seed_rung,
)
from src.core.session_transcript_status_read import (
    read_transcript_signal,
    transcript_status_for,
)
from src.core.hosts.ddl import LOCAL_HOST_KEY, host_scope

logger = structlog.get_logger(__name__)

_STORES: "WeakKeyDictionary[Any, SessionStatusSeeds]" = WeakKeyDictionary()

_SEED_READ_ERRORS: Tuple[type, ...] = (sqlite3.Error, OSError, ValueError, KeyError)


def seeds_for(manager: Any) -> SessionStatusSeeds:
    try:
        store = _STORES.get(manager)
        if store is None:
            store = SessionStatusSeeds()
            _STORES[manager] = store
        return store
    except TypeError:
        return SessionStatusSeeds()


def read_transcript_rest(
    uuid: Optional[str],
    working_dir: Optional[str],
    *,
    session_id: Optional[str] = None,
) -> TranscriptRest:
    """What the tail of a conversation's transcript says about rest.

    Description: resolves the uuid to a file through
      ``conversation_presence`` and classifies the last decidable record
      in the bounded tail window. THREE REFUSALS, kept apart: no uuid
      bound to the row, a MEASURED absent transcript, and a file that
      could not be read. None of them is evidence of rest, and only the
      middle one is evidence of anything.
    Inputs: uuid (str | None) - ``sessions.claude_session_uuid``.
      working_dir (str | None) - used only for the fast-path slug.
      session_id (str | None) - for the failure log only; this function
      never uses it to look anything up.
    Output: TranscriptRest.
    Example: read_transcript_rest(uuid, '/Users/x/proj').verdict
    """
    return read_transcript_signal(
        uuid, working_dir, session_id=session_id
    ).tail


def read_instance_row(
    manager: Any,
    tmux_name: Optional[str],
    epoch: Optional[int],
    *,
    session_id: Optional[str] = None,
    index: Optional[Any] = None,
    host_key: str = LOCAL_HOST_KEY,
) -> Optional[Dict[str, Any]]:
    if not tmux_name or epoch is None:
        return None
    if index is not None and getattr(index, "complete", False):
        return index.seed_row(tmux_name, epoch)
    conn = None
    try:
        conn = manager._writable_datastore_connection()
        if conn is None:
            return None
        scope_sql, scope_params = host_scope(conn, host_key)
        row = conn.execute(
            "SELECT activity_state, activity_state_at, claude_session_uuid, "
            f"working_dir FROM sessions WHERE tmux_socket = ?{scope_sql} AND "
            "tmux_name = ? AND tmux_created_epoch = ?",
            (manager._tmux_socket_name(), *scope_params, tmux_name, int(epoch)),
        ).fetchone()
        if not row:
            return None
        return {
            "activity_state": row[0],
            "activity_state_at": row[1],
            "claude_session_uuid": row[2],
            "working_dir": row[3],
        }
    except _SEED_READ_ERRORS as exc:
        logger.warning(
            "status_seed_row_read_failed",
            session_id=session_id,
            tmux_name=tmux_name,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def _resolve_epoch(
    manager: Any, session_id: str, epoch: Optional[int]
) -> Optional[int]:
    if epoch is not None:
        return epoch
    return (getattr(manager, "_instance_epochs", None) or {}).get(session_id)


def derive_seed(
    manager: Any,
    session_id: str,
    tmux_name: Optional[str],
    *,
    epoch: Optional[int] = None,
    unread: bool = False,
    now: Optional[datetime] = None,
    index: Optional[Any] = None,
) -> StatusSeed:
    epoch = _resolve_epoch(manager, session_id, epoch)
    stamp = now or datetime.now(timezone.utc)

    row = read_instance_row(
        manager, tmux_name, epoch, session_id=session_id, index=index
    )
    if row is None:
        return StatusSeed(
            rung=SEED_RUNG_NONE,
            detail=(
                "this session's exact tmux instance could not be "
                "identified, so no row and no transcript were consulted"
            ),
        )

    reading = read_transcript_signal(
        row.get("claude_session_uuid"),
        row.get("working_dir"),
        session_id=session_id,
    )
    live = transcript_status_for(
        manager,
        session_id=session_id,
        tmux_name=tmux_name,
        epoch=epoch,
        reading=reading,
        unread=unread,
        now=stamp,
    )
    return resolve_status_seed(
        row_state=row.get("activity_state"),
        row_state_at=row.get("activity_state_at"),
        tail=reading.tail,
        live=live,
        now=stamp,
    )


def seeded_status(
    manager: Any,
    session_id: str,
    tmux_name: Optional[str],
    *,
    epoch: Optional[int] = None,
    unread: bool = False,
    now: Optional[datetime] = None,
    index: Optional[Any] = None,
) -> Optional[str]:
    return seeded_display(
        manager,
        session_id,
        tmux_name,
        epoch=epoch,
        unread=unread,
        now=now,
        index=index,
    )[0]


def seeded_display(
    manager: Any,
    session_id: str,
    tmux_name: Optional[str],
    *,
    epoch: Optional[int] = None,
    unread: bool = False,
    now: Optional[datetime] = None,
    index: Optional[Any] = None,
) -> Tuple[Optional[str], str]:
    try:
        store = seeds_for(manager)
        stamp = now or datetime.now(timezone.utc)
        resolved_epoch = _resolve_epoch(manager, session_id, epoch)
        if store.due(session_id, now=stamp, epoch=resolved_epoch):
            seed = derive_seed(
                manager,
                session_id,
                tmux_name,
                epoch=resolved_epoch,
                unread=unread,
                now=stamp,
                index=index,
            )
            store.remember(session_id, seed, now=stamp, epoch=resolved_epoch)
        else:
            seed = store.get(session_id) or StatusSeed()
        state = display_state(seed, unread=unread, now=stamp)
        if state is None:
            return (None, STATUS_SOURCE_NONE)
        return (state, source_for_seed_rung(seed.rung))
    except _SEED_READ_ERRORS as exc:
        logger.warning(
            "status_seed_failed",
            session_id=session_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return (None, STATUS_SOURCE_NONE)


def seed_live_sessions(manager: Any) -> Tuple[int, int]:
    seeded = 0
    examined = 0
    try:
        sessions = dict(manager._registry.sessions)
        store = seeds_for(manager)
        store.prune(sessions.keys())
        now = datetime.now(timezone.utc)
    except _SEED_READ_ERRORS as exc:
        logger.warning(
            "status_seed_warm_setup_failed",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return (0, 0)

    for session_id, session in sessions.items():
        try:
            examined += 1
            authority = getattr(manager, "hook_tokens", None)
            tmux_name = getattr(session, "tmux_session", None) or (
                authority.name_for(session_id) if authority is not None else None
            )
            resolved_epoch = _resolve_epoch(manager, session_id, None)
            seed = derive_seed(
                manager, session_id, tmux_name, epoch=resolved_epoch, now=now
            )
            store.remember(session_id, seed, now=now, epoch=resolved_epoch)
            if seed.seeds:
                seeded += 1
        except _SEED_READ_ERRORS as exc:
            logger.warning(
                "status_seed_warm_one_failed",
                session_id=session_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            continue
    logger.info("status_seed_warm", seeded=seeded, examined=examined)
    return (seeded, examined)
