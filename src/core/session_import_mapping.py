
from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional

from src.core.project_attribution import attribute


def attribute_working_dir(
    working_dir: Optional[str], roots: Dict[str, int]
) -> tuple[Optional[int], str]:
    return attribute(working_dir, roots)


def _project_roots(conn: sqlite3.Connection) -> Dict[str, int]:
    try:
        rows = conn.execute("SELECT root, id FROM projects").fetchall()
    except sqlite3.Error:
        return {}
    return {str(row[0]): int(row[1]) for row in rows}


def _row_fields(row: Any) -> Dict[str, Any]:
    if isinstance(row, str):
        return {"name": row, "tmux_created_epoch": None}
    if isinstance(row, dict):
        name = row.get("name")
        epoch = row.get("created_at_epoch", row.get("tmux_created_epoch"))
        try:
            epoch_int: Optional[int] = int(epoch)
        except (TypeError, ValueError):
            epoch_int = None
        return {
            "name": name,
            "tmux_created_epoch": epoch_int,
            "working_dir": row.get("working_dir"),
            "tmux_session_id": row.get("tmux_session_id"),
        }
    return {"name": None, "tmux_created_epoch": None}


def _merge_fields(entry: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not entry:
        return {}
    mapping = {
        "agent_type": entry.get("agent_type"),
        "model": entry.get("model"),
        "pinned_theme": entry.get("pinned_theme"),
        "legacy_session_id": entry.get("id") or entry.get("session_id"),
        "title": entry.get("title"),
        "unread_auto": entry.get("unread_auto"),
        "unread_manual": entry.get("unread_manual"),
    }
    return {key: value for key, value in mapping.items() if value is not None}


def _persisted_session_id(entry: Dict[str, Any]) -> Optional[str]:
    value = entry.get("tmux_session_id")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _stopped_epoch(entry: Dict[str, Any]) -> Optional[int]:
    for key in ("tmux_created_epoch", "created_at_epoch"):
        value = entry.get(key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return None
