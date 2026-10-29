
from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

import structlog

from src.core.bookmarks import cut, locate, rows, store, transcript_index
from src.core.bookmarks.copy_writer import write_copy
from src.core.bookmarks.errors import BookmarkError, EntryNotFound, TranscriptChanged

logger = structlog.get_logger()

POINT_TURN = "turn"
POINT_NOW = "now"
POINTS = (POINT_TURN, POINT_NOW)
MAX_TURNS_PAGE = 200


def _index_for(conversation: str, working_dir: Optional[str]) -> transcript_index.TranscriptIndex:
    return transcript_index.cached_index(locate.find_transcript(conversation, working_dir))


def add_bookmark(session_uuid: str, *, label: str = "", entry_uuid: Optional[str] = None,
                 point: str = POINT_TURN, created_by: str = "owner") -> store.Bookmark:
    if point not in POINTS:
        raise BookmarkError(f"point must be one of {', '.join(POINTS)}")
    row = rows.read_row(session_uuid)
    conversation = rows.require_bookmarkable(row)
    index = _index_for(conversation, row.working_dir)
    if entry_uuid:
        node = index.nodes.get(entry_uuid)
    elif point == POINT_TURN:
        node = transcript_index.latest_turn(index)
    else:
        node = index.nodes.get(index.leaf() or "")
    if node is None:
        raise EntryNotFound("that point is not in this session's conversation yet")
    opened = transcript_index.marked_turn(index, node)
    snippet = opened.snippet if opened is not None else ""
    try:
        return store.get_store().add(
            session_uuid=row.session_uuid, session_row_id=row.id, claude_session_uuid=conversation,
            entry_uuid=node.uuid, label=label, created_by=created_by, snippet=snippet,
            entry_timestamp=node.timestamp)
    except ValueError as exc:
        raise BookmarkError(str(exc)) from exc


def list_bookmarks(session_uuid: str) -> dict:
    row = rows.read_row(session_uuid)
    return {
        "session_uuid": row.session_uuid,
        "conversation": row.claude_session_uuid,
        "family": rows.family_of(row.agent_type),
        "bookmarks": [b.as_dict() for b in store.get_store().list_for_session(row.session_uuid)],
        "compactions": [],
    }


def list_all(limit: int = store.MAX_RECENT) -> dict:
    marks = store.get_store().list_recent(limit)
    found = rows.labels_for([m.session_uuid for m in marks])
    out = []
    for mark in marks:
        row = found.get(mark.session_uuid)
        out.append({**mark.as_dict(),
                    "session_label": (row.title or row.tmux_name or "") if row else "",
                    "session_tmux": (row.tmux_name or "") if row else "",
                    "family": rows.family_of(row.agent_type) if row else ""})
    return {"bookmarks": out, "compactions": []}


def delete_bookmark(bookmark_id: int) -> store.Bookmark:
    return store.get_store().delete(bookmark_id)


def turns_page(session_uuid: str, *, offset: int = 0, limit: int = 50) -> dict:
    row = rows.read_row(session_uuid)
    conversation = rows.require_bookmarkable(row)
    found = transcript_index.turns(_index_for(conversation, row.working_dir))
    offset = max(0, int(offset))
    limit = min(MAX_TURNS_PAGE, max(1, int(limit)))
    total = len(found)
    page = [{"entry_uuid": n.uuid, "snippet": n.snippet, "timestamp": n.timestamp, "number": total - offset - i}
            for i, n in enumerate(found[offset:offset + limit])]
    return {"session_uuid": row.session_uuid, "conversation": conversation, "total": total, "turns": page}


def cut_copy(conversation: str, entry_uuid: str, working_dir: Optional[str]) -> Tuple[str, Path]:
    source = locate.resolve_transcript(conversation, working_dir)
    dest = locate.destination_dir(source, working_dir)
    index = transcript_index.cached_index(source)
    try:
        return write_copy(index, cut.kept_chain(index, entry_uuid), dest)
    except TranscriptChanged:
        logger.info("bookmark_copy_retry", conversation=conversation)
        fresh = transcript_index.build_index(source)
        return write_copy(fresh, cut.kept_chain(fresh, entry_uuid), dest)
