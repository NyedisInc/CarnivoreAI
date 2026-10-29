
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.core.bookmarks import store

logger = structlog.get_logger()


def closest(marks: List[store.Bookmark], at: Optional[str]) -> Optional[Dict[str, Any]]:
    if not at:
        return None
    for mark in marks:
        if mark.entry_timestamp >= at:
            return {"id": mark.id, "label": mark.label, "at": mark.entry_timestamp}
    return None


def read_marks(state_dir: Path, conversation_ids: List[str]) -> List[store.Bookmark]:
    path = Path(state_dir) / store.DB_FILENAME
    if not conversation_ids or not path.exists():
        return []
    try:
        return store.BookmarkStore(path).list_for_conversations(conversation_ids)
    except (sqlite3.Error, OSError) as exc:
        logger.warning("deepsearch_bookmarks_unreadable", error_type=type(exc).__name__)
        return []


def attach(state_dir: Path, groups: List[Dict[str, Any]]) -> None:
    for group in groups:
        for hit in group["hits"]:
            hit["bookmark"] = None
    marks = read_marks(state_dir, [g["conversation_id"] for g in groups if g["hits"]])
    by_conversation: Dict[str, List[store.Bookmark]] = {}
    for mark in marks:
        by_conversation.setdefault(mark.claude_session_uuid, []).append(mark)
    for group in groups:
        mine = by_conversation.get(group["conversation_id"], [])
        for hit in group["hits"]:
            hit["bookmark"] = closest(mine, hit.get("at"))
