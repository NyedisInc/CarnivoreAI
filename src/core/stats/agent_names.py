from __future__ import annotations

import sqlite3
import threading
import time
from typing import Dict, Optional, Tuple

import structlog

from src.core.db import DatastoreUnreadableError, connect, db_path_for
from src.core.product_identity import strip_session_prefix

logger = structlog.get_logger()

CACHE_SECONDS = 30.0
UNNAMED = "unnamed agent"

_lock = threading.Lock()
_cache: Dict[str, Tuple[float, Dict[str, str]]] = {}


def root_of(conversation_id: str) -> str:
    return conversation_id.split(":", 1)[0]


def _name_of(title: Optional[str], tmux_name: Optional[str]) -> Optional[str]:
    if title and title.strip():
        return title.strip()
    if tmux_name:
        return strip_session_prefix(tmux_name) or tmux_name
    return None


def resolve(store) -> Dict[str, str]:
    try:
        app_db = connect(db_path_for(store.state_dir), create=False)
    except DatastoreUnreadableError as exc:
        logger.warning("stats_agent_names_app_db_unreadable", error=str(exc))
        return {}
    names: Dict[str, str] = {}
    try:
        rows = app_db.execute(
            "SELECT claude_session_uuid, title, tmux_name FROM sessions "
            "WHERE claude_session_uuid IS NOT NULL AND claude_session_uuid != '' ORDER BY id").fetchall()
    except sqlite3.Error as exc:
        logger.warning("stats_agent_names_failed", error=str(exc))
        return {}
    finally:
        app_db.close()
    for uuid, title, tmux_name in rows:
        name = _name_of(title, tmux_name)
        if name:
            names[uuid] = name
    return names


def names_for(store, *, now: Optional[float] = None) -> Dict[str, str]:
    clock = time.monotonic() if now is None else now
    key = str(store.state_dir)
    with _lock:
        hit = _cache.get(key)
        if hit is not None and clock - hit[0] < CACHE_SECONDS:
            return hit[1]
    fresh = resolve(store)
    with _lock:
        _cache[key] = (clock, fresh)
    return fresh


def forget() -> None:
    with _lock:
        _cache.clear()
