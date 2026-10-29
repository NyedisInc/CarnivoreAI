
from __future__ import annotations

import sqlite3
from typing import Any, Optional

import structlog

logger = structlog.get_logger()

from src.core.db_models import SESSION_CLAUDE_UUID_SOURCE_CODEX_THREAD_MAP

_LIFECYCLE_SESSION_START = "SessionStart"

# : conversation,
_PAYLOAD_SOURCE_REGISTRY = "registry"


def codex_bind_conversation(
    manager: Any,
    *,
    session_id: str,
    tmux_name: Optional[str],
    thread_uuid: Optional[str],
    epoch: Optional[int] = None,
    pane_owned: bool = False,
) -> Any:
    if not tmux_name or not thread_uuid:
        return
    if pane_owned and epoch is not None:
        return _bind_owned_conversation(manager, tmux_name, epoch, thread_uuid)
    return manager.record_claude_lifecycle_event(
        session_id,
        _LIFECYCLE_SESSION_START,
        {"session_id": thread_uuid, "source": _PAYLOAD_SOURCE_REGISTRY},
        uuid_source=SESSION_CLAUDE_UUID_SOURCE_CODEX_THREAD_MAP,
        tmux_name=tmux_name,
    )


def _bind_owned_conversation(
    manager: Any, tmux_name: str, epoch: int, thread_uuid: str,
) -> Any:
    from src.core.db import transaction
    from src.core.session_claude_correlate_bind import (
        BIND_UNRESOLVED, BindResult, bind_correlated_uuid,
    )
    from src.core.session_store import get_instance

    conn = manager._writable_datastore_connection()
    if conn is None:
        return BindResult(outcome=BIND_UNRESOLVED, detail="datastore unavailable")
    try:
        socket = manager._tmux_socket_name()
        with transaction(conn):
            row = get_instance(conn, socket=socket, name=tmux_name, epoch=epoch)
            if row is None:
                return BindResult(outcome=BIND_UNRESOLVED, detail="instance row unavailable")
            return bind_correlated_uuid(
                conn, socket=socket, name=tmux_name, epoch=epoch,
                claude_uuid=thread_uuid, source=SESSION_CLAUDE_UUID_SOURCE_CODEX_THREAD_MAP,
                replaces_uuid=row.get("claude_session_uuid"),
            )
    except (sqlite3.Error, OSError, ValueError) as exc:
        logger.warning("codex_conversation_bind_failed", tmux_name=tmux_name,
                       error_type=type(exc).__name__)
        return BindResult(outcome=BIND_UNRESOLVED, detail="conversation write unavailable")
    finally:
        conn.close()
