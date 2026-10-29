
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

logger = structlog.get_logger()

_NAME_SQL = "COALESCE(NULLIF(title, ''), NULLIF(claude_title, ''), NULLIF(tmux_name, ''))"
NAME_CHARS: int = 120


def main_db_path() -> Path:
    from src.config import settings
    from src.core.db import db_path_for

    return db_path_for(settings.get_state_dir())


def session_name(db_path: Path, tmux_name: str) -> Optional[str]:
    from src.core.db import DatastoreUnreadableError, connect

    try:
        conn = connect(Path(db_path), create=False)
    except (DatastoreUnreadableError, sqlite3.Error) as exc:
        logger.debug("automation_run_by_db_unreadable", error=type(exc).__name__)
        return None
    try:
        row = conn.execute(f"SELECT {_NAME_SQL} FROM sessions WHERE tmux_name = ? ORDER BY id DESC LIMIT 1",
                           (tmux_name,)).fetchone()
    except sqlite3.Error as exc:
        logger.warning("automation_run_by_lookup_failed", error=type(exc).__name__)
        return None
    finally:
        conn.close()
    return str(row[0])[:NAME_CHARS] if row and row[0] else None


def owner_name(preferences: Any) -> Optional[str]:
    from src.core.owner_identity.identity import os_account_full_name

    chosen = preferences.read()["values"].get("owner_display_name") if preferences is not None else None
    name = chosen or os_account_full_name()
    return str(name)[:NAME_CHARS] if name else None


def with_name(actor: Dict[str, Any], db_path: Optional[Path], owner: Optional[str] = None) -> Dict[str, Any]:
    out = dict(actor)
    if out.get("name"):
        return out
    if out.get("kind") == "app":
        if owner:
            out["name"] = owner[:NAME_CHARS]
        return out
    if out.get("kind") != "mcp":
        return out
    tmux = str(out.get("tmux") or "")
    name = session_name(db_path, tmux) if db_path is not None and tmux and not out.get("client") else None
    name = name or (str(out["client"])[:NAME_CHARS] if out.get("client") else None)
    if name:
        out["name"] = name
    return out
