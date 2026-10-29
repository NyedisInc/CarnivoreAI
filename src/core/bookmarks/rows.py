
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Sequence

import structlog

from src.core.bookmarks.errors import BookmarkError, NoConversation, NotClaudeSession, SessionNotFound

logger = structlog.get_logger()

_COLUMNS = ("id, session_uuid, claude_session_uuid, claude_session_uuid_source, working_dir, title, tmux_name, "
            "tmux_socket, agent_type, model, launch_record")


@dataclass(frozen=True)
class SessionRow:

    id: int
    session_uuid: str
    claude_session_uuid: Optional[str]
    claude_session_uuid_source: Optional[str]
    working_dir: Optional[str]
    title: Optional[str]
    tmux_name: Optional[str]
    tmux_socket: Optional[str]
    agent_type: Optional[str]
    model: Optional[str]
    launch_record: Optional[str]
    host_key: str = "local"


def db_path() -> Path:
    from src.config import settings
    from src.core.db import db_path_for

    return db_path_for(settings.get_state_dir())


def read_row(session_uuid: str, path: Optional[Path] = None) -> SessionRow:
    from src.core.db import DatastoreUnreadableError, connect

    target = path or db_path()
    if not target.exists():
        raise SessionNotFound("no datastore yet, so there is no session")
    try:
        with closing(connect(target, create=False)) as conn:
            key = "id" if str(session_uuid).isdigit() else "session_uuid"
            row = conn.execute(f"SELECT {_COLUMNS} FROM sessions WHERE {key} = ? LIMIT 1",
                               (int(session_uuid) if key == "id" else session_uuid,)).fetchone()
            host = _host_key(conn, row["session_uuid"]) if row is not None else "local"
    except (DatastoreUnreadableError, sqlite3.Error) as exc:
        error = BookmarkError(f"the session store could not be read: {exc}")
        error.status, error.code = 503, "datastore_unreadable"
        raise error from exc
    if row is None:
        raise SessionNotFound("no session with that id")
    return SessionRow(**dict(row), host_key=host)


def labels_for(session_uuids: Sequence[str], path: Optional[Path] = None) -> Dict[str, SessionRow]:
    from src.core.db import DatastoreUnreadableError, connect

    wanted = sorted({u for u in session_uuids if u})
    target = path or db_path()
    if not wanted or not target.exists():
        return {}
    try:
        with closing(connect(target, create=False)) as conn:
            found = conn.execute(
                f"SELECT {_COLUMNS} FROM sessions WHERE session_uuid IN ({','.join('?' * len(wanted))})", wanted).fetchall()
    except (DatastoreUnreadableError, sqlite3.Error) as exc:
        logger.warning("bookmark_labels_unreadable", error=str(exc))
        return {}
    return {r["session_uuid"]: SessionRow(**dict(r)) for r in found}


def _host_key(conn: sqlite3.Connection, session_uuid: str) -> str:
    try:
        row = conn.execute("SELECT host_key FROM sessions WHERE session_uuid = ?", (session_uuid,)).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such column" in str(exc):
            return "local"
        raise
    return str(row[0]) if row is not None and row[0] else "local"


def family_of(agent_type: Optional[str]) -> str:
    from src.config import settings
    from src.core.agent_families import get_family, resolve_agent_type

    try:
        wrappers = settings.load_auth_config().agents.wrappers
    except (ValueError, OSError) as exc:
        logger.debug("bookmark_family_wrappers_unreadable", error=str(exc))
        return get_family(agent_type).name
    return resolve_agent_type(agent_type, wrappers)[0].name


def require_bookmarkable(row: SessionRow) -> str:
    family = family_of(row.agent_type)
    if family != "claude":
        raise NotClaudeSession(f"bookmarks work on claude code sessions only; this one runs {family}")
    if row.host_key != "local":
        error = BookmarkError("this session runs on a paired computer; open bookmarks there")
        error.status, error.code = 409, "remote_host"
        raise error
    if not row.claude_session_uuid:
        raise NoConversation("this session has no recorded claude conversation yet")
    return row.claude_session_uuid


def swap_conversation(row_id: int, old: str, new: str, path: Optional[Path] = None,
                      source: Optional[str] = None) -> bool:
    from src.core.db import DatastoreUnreadableError, connect, transaction
    from src.core.db_models import SESSION_CLAUDE_UUID_SOURCE_BOOKMARK_REWIND
    from src.core.trail_entry import utc_now

    try:
        with closing(connect(path or db_path(), create=False)) as conn, transaction(conn):
            cur = conn.execute(
                "UPDATE sessions SET claude_session_uuid = ?, claude_session_uuid_source = ?, updated_at = ? "
                "WHERE id = ? AND claude_session_uuid = ?",
                (new, source or SESSION_CLAUDE_UUID_SOURCE_BOOKMARK_REWIND, utc_now(), row_id, old))
            moved = cur.rowcount == 1
    except sqlite3.IntegrityError as exc:
        logger.warning("bookmark_swap_conflict", row_id=row_id, new=new, error=str(exc))
        return False
    except (DatastoreUnreadableError, sqlite3.Error) as exc:
        logger.warning("bookmark_swap_failed", row_id=row_id, error=str(exc))
        return False
    logger.info("bookmark_conversation_swapped", row_id=row_id, previous=old, conversation=new, moved=moved)
    return moved
