from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict

import structlog

from src.core.db import DatastoreUnreadableError, connect, db_path_for
from src.core.session_recreate import has_tmux_identity
from src.core import restart_live_gate
from src.core.session_recreate_presence import (
    TMUX_PRESENT,
    TMUX_UNKNOWN,
    TmuxPresence,
    epoch_marks_other_instance,
    presence_as_other_instance,
    tmux_presence,
)
from src.core.sessions.errors import SessionError, SessionNotFound, SessionNotRunning

logger = structlog.get_logger()


class RowError(SessionError):
    pass


class RowDatastoreUnreadable(RowError):
    pass


class RowNotFound(RowError, SessionNotFound):
    pass


class RowOnRemoteHost(RowError, SessionNotRunning):
    pass


class RowNeverHadTmux(RowError, SessionNotRunning):
    pass


class UnsafeTmuxName(RowError):

    def __init__(self, message: str, name: str = "") -> None:
        super().__init__(message)
        self.name = name


def db_path() -> Path:
    from src.config import settings

    return db_path_for(settings.get_state_dir())


def socket_name() -> str:
    from src.config import settings
    from src.core.tmux_backend import DEFAULT_SOCKET_NAME

    try:
        return settings.load_auth_config().session.tmux_socket_name
    except (OSError, ValueError, AttributeError):
        return DEFAULT_SOCKET_NAME


def measure_presence(name: str, socket_name: str) -> TmuxPresence:
    from src.config import settings
    from src.core.tmux_backend import SESSION_PREFIX, TmuxBackend

    try:
        probe = TmuxBackend.for_external(
            session_name=name,
            working_dir=Path(settings.default_working_dir).expanduser(),
            on_output=None,
            socket_name=socket_name,
        )
        listing = probe.discover_existing()
    except (OSError, ValueError, AttributeError) as exc:
        logger.warning("recreate_presence_unmeasured", name=name, error=str(exc))
        return TmuxPresence(
            outcome=TMUX_UNKNOWN,
            detail=(
                "the tmux socket could not be listed, so whether this "
                "session is still running was not evaluated"
            ),
        )
    return tmux_presence(
        name,
        listing_ok=bool(listing.ok),
        listing_complete=bool(listing.complete),
        names=list(listing.sessions or []),
        namespace_prefix=SESSION_PREFIX,
    )


def measure_row_presence(row: Dict[str, Any], name: str, socket_name: str) -> TmuxPresence:
    presence = measure_presence(name, socket_name)
    epoch = row.get("tmux_created_epoch")
    if presence.outcome != TMUX_PRESENT or epoch is None:
        return presence
    observed = restart_live_gate.probe_epoch(restart_live_gate.probe_line(name, socket_name), name)
    if epoch_marks_other_instance(epoch, observed):
        return presence_as_other_instance(presence)
    return presence


def read_row(session_uuid: str) -> Dict[str, Any]:
    try:
        with closing(connect(db_path(), create=False)) as conn:
            found = conn.execute(
                "SELECT * FROM sessions WHERE session_uuid = ?", (session_uuid,)
            ).fetchone()
    except (DatastoreUnreadableError, OSError) as exc:
        logger.warning(
            "recreate_row_unreadable", session_uuid=session_uuid, error=str(exc)
        )
        return {"row": None, "row_read_ok": False}
    return {"row": dict(found) if found is not None else None, "row_read_ok": True}


def resolve_row(state: Dict[str, Any], session_uuid: str) -> Dict[str, Any]:
    if not state["row_read_ok"]:
        raise RowDatastoreUnreadable("the datastore could not be read, so this session's recreate could not be evaluated")
    row = state["row"]
    if row is None:
        raise RowNotFound(f"no session carries the uuid {session_uuid!r}")
    if (row.get("host_key") or "local") != "local":
        raise RowOnRemoteHost(f"session {session_uuid!r} runs on host {row['host_key']}; "
                              "a remote session is never recreated on this machine")
    if not has_tmux_identity(row):
        raise RowNeverHadTmux(f"session {session_uuid!r} has never had a tmux session, so it restarts through "
                              "GET /sessions/imported/restart/preview and POST /sessions/imported/restart")
    return row


def safe_name(name: str) -> str:
    from src.core.tmux_transport.target import check_target_name  # noqa: PLC0415

    try:
        return check_target_name(name)
    except ValueError as exc:
        raise UnsafeTmuxName(str(exc), name=name) from exc


def stored_host_key(conn: sqlite3.Connection, session_uuid: str) -> str:
    try:
        row = conn.execute("SELECT host_key FROM sessions WHERE session_uuid = ?", (session_uuid,)).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such column" in str(exc) or "no such table" in str(exc):
            return "local"
        raise
    return str(row[0]) if row is not None and row[0] else "local"
