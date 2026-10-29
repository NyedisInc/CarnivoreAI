
from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from typing import Optional

import structlog

from src.core.safe_io.readonly_db import READONLY_TIMEOUT_DEFAULT_S, connect_readonly
from src.core.transcript_manifest import store

logger = structlog.get_logger(__name__)

_lock = threading.Lock()
_db_path: Optional[Path] = None


def configure(db_path: Optional[Path]) -> None:
    global _db_path
    with _lock:
        _db_path = Path(db_path) if db_path is not None else None


def transcript_path(conversation_id: Optional[str], family: Optional[str], *,
                    conn: Optional[sqlite3.Connection] = None) -> Optional[Path]:
    path = _db_path
    if path is None or not conversation_id:
        return None
    try:
        if conn is not None:
            found = store.path_for_conversation(conn, str(conversation_id), family)
        else:
            with closing(connect_readonly(path, timeout=READONLY_TIMEOUT_DEFAULT_S)) as own:
                found = store.path_for_conversation(own, str(conversation_id), family)
    except (sqlite3.Error, OSError) as exc:
        logger.warning("transcript_manifest_lookup_failed", conversation_id=conversation_id, error=str(exc))
        return None
    if found is None:
        return None
    candidate = Path(found)
    try:
        return candidate if candidate.is_file() else None
    except OSError:
        return None
