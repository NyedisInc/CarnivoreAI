
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.core.bookmarks import compactions, locate, rows, store, transcript_index
from src.core.bookmarks.errors import BookmarkError
from src.core.lineage import graph, timeline
from src.core.session_timeline import activity, attention, wake
from src.core.session_timeline.assemble import Sources, assemble

logger = structlog.get_logger()


def _entries(db: Path, row: rows.SessionRow) -> List[Dict[str, Any]]:
    from src.core.db import DatastoreUnreadableError, connect

    found: List[Dict[str, Any]] = []
    try:
        with closing(connect(db, create=False)) as conn:
            if graph.ready(conn):
                found = timeline.session_timeline(conn, row.session_uuid) or []
    except (DatastoreUnreadableError, sqlite3.Error) as exc:
        logger.warning("session_timeline_lineage_unreadable", error=str(exc))
    if not found and row.claude_session_uuid:
        found = [{"conversation_id": row.claude_session_uuid, "current": True, "level": None, "began": None,
                  "milestones": []}]
    return found


def _bookmarks(session_uuid: str) -> List[Dict[str, Any]]:
    try:
        return [b.as_dict() for b in store.get_store().list_for_session(session_uuid)]
    except (sqlite3.Error, OSError) as exc:
        logger.warning("session_timeline_bookmarks_unreadable", error=str(exc))
        return []


def _points(conversations: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    from src.cplugs.sdk import restore_points  # noqa: PLC0415

    port = restore_points.get()
    out: Dict[str, List[Dict[str, Any]]] = {}
    if port is None:
        return out
    for conv in conversations:
        try:
            out[conv] = port.list_points(conv)
        except (OSError, ValueError) as exc:
            logger.warning("session_timeline_points_unreadable", conversation=conv, error=str(exc))
    return out


def _split_times(entries: List[Dict[str, Any]], working_dir: Optional[str]) -> Dict[Tuple[str, str], str]:
    out: Dict[Tuple[str, str], str] = {}
    for entry in entries:
        split = (entry.get("began") or {}).get("split") or {}
        conv, message = split.get("conversation"), split.get("message_uuid")
        if not conv or not message or (conv, message) in out:
            continue
        try:
            node = transcript_index.cached_index(locate.find_transcript(conv, working_dir)).nodes.get(message)
        except BookmarkError as exc:
            logger.debug("session_timeline_split_undated", conversation=conv, reason=str(exc))
            continue
        if node is not None and node.timestamp:
            out[(conv, message)] = node.timestamp
    return out


def _db_path() -> Path:
    return rows.db_path()


def _stats_db(db: Path) -> Path:
    from src.core.pipeline import plugin_db  # noqa: PLC0415
    from src.core.stats.plugin.pipeline_plugin import STATS  # noqa: PLC0415

    return plugin_db.db_path(db.parent, STATS)


def build(session_key: str, *, now: Optional[datetime] = None, db: Optional[Path] = None,
          stats_db: Optional[Path] = None) -> Dict[str, Any]:
    db = db or _db_path()
    row = rows.read_row(session_key, db)
    entries = _entries(db, row)
    conversations = [e["conversation_id"] for e in entries]
    family = rows.family_of(row.agent_type)
    is_claude = family == "claude"
    src = Sources(
        session={"session_uuid": row.session_uuid, "row_id": row.id, "family": family,
                 "current": row.claude_session_uuid},
        entries=entries, now=now or datetime.now(timezone.utc),
        compacts={c: compactions.list_compactions(c, row.working_dir, db) for c in conversations} if is_claude else {},
        bookmarks=_bookmarks(row.session_uuid) if is_claude else [],
        points=_points(conversations),
        split_times=_split_times(entries, row.working_dir) if is_claude else {})
    answer = attention.attach(assemble(src), db.parent)
    if wake.is_running(db, row.session_uuid):
        answer = wake.close_gaps(answer)
    return activity.attach(answer, stats_db or _stats_db(db))


def conversations_of(session_key: str, db: Optional[Path] = None) -> Tuple[rows.SessionRow, List[str]]:
    db = db or _db_path()
    row = rows.read_row(session_key, db)
    return row, [e["conversation_id"] for e in _entries(db, row)]

