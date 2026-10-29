
from __future__ import annotations

import json
import sqlite3
from contextlib import ExitStack, closing
from pathlib import Path
from typing import Dict, List, Optional

import structlog

from src.core import item_catalog
from src.core.attention.transcript_records import record_text
from src.core.bookmarks import compactions, locate, predecessor, rows, store, transcript_index
from src.core.bookmarks.errors import EntryNotFound, TranscriptUnavailable

logger = structlog.get_logger()

SETTINGS_WIDGET_ID = "core.bookmarks"
SETTINGS_KEY = "previewTurns"
MAX_PREVIEW_TURNS = 20
PART_CHARS = 600
MAX_WALK = 5000
MAX_FILE_HOPS = 5


def configured_turns(db_path: Optional[Path] = None) -> int:
    decl = item_catalog.find("widget", SETTINGS_WIDGET_ID)
    field = decl.schema.fields.get(SETTINGS_KEY, {}) if decl is not None and decl.schema is not None else {}
    value = field.get("default", 1)
    path = db_path or rows.db_path()
    if decl is not None and path.exists():
        try:
            from src.core import item_settings_store
            from src.core.db import connect

            with closing(connect(path, create=False)) as conn:
                value = item_settings_store.read_item(conn, "widget", SETTINGS_WIDGET_ID).values.get(SETTINGS_KEY, value)
        except (sqlite3.Error, OSError) as exc:
            logger.warning("bookmark_preview_setting_unreadable", error=str(exc))
    return clamp_turns(value)


def clamp_turns(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 1
    return max(1, min(MAX_PREVIEW_TURNS, int(value)))


def _record_at(stream, node: transcript_index.Node) -> Optional[dict]:
    stream.seek(node.offset)
    try:
        record = json.loads(stream.read(node.length))
    except ValueError:
        logger.debug("bookmark_preview_span_unreadable", uuid=node.uuid)
        return None
    return record if isinstance(record, dict) and record.get("uuid") == node.uuid else None


def _text_of(record: dict, role: str) -> str:
    if role == "user":
        peer = transcript_index.peer_turn_text(record)
        return (peer if peer is not None else record_text(record)).strip()
    return record_text(record).strip()


def _before_boundary(index: transcript_index.TranscriptIndex, boundary: transcript_index.Node,
                     seen: set) -> Optional[transcript_index.Node]:
    try:
        at = index.order.index(boundary.uuid)
    except ValueError:
        return None
    for uuid in reversed(index.order[:at]):
        if uuid not in seen:
            return index.nodes.get(uuid)
    return None


def preview_parts(path: Path, entry_uuid: str, turns: int) -> List[Dict[str, object]]:
    limit = clamp_turns(turns)
    index = transcript_index.cached_index(path)
    cursor = index.nodes.get(entry_uuid)
    if cursor is None:
        raise EntryNotFound("that bookmark's point is not in its transcript")
    found: List[Dict[str, object]] = []
    msg_ids: List[Optional[str]] = []
    seen = set()
    boundaries: List[transcript_index.Node] = []
    hops = 0
    try:
        with ExitStack() as stack:
            stream = stack.enter_context(path.open("rb"))
            while cursor is not None and cursor.uuid not in seen and len(seen) < MAX_WALK:
                seen.add(cursor.uuid)
                role = "assistant" if cursor.kind == "assistant" and not cursor.tool_uses else "user" if cursor.turn_start else ""
                if role:
                    record = _record_at(stream, cursor)
                    text = _text_of(record, role) if record is not None else ""
                    joins = bool(found) and role == "assistant" and cursor.msg_id and msg_ids[-1] == cursor.msg_id
                    if text and joins:
                        found[-1]["text"] = f"{text}\n{found[-1]['text']}"
                    elif text:
                        if len(found) == limit:
                            break
                        found.append({"entry_uuid": cursor.uuid, "role": role, "text": text, "timestamp": cursor.timestamp})
                        msg_ids.append(cursor.msg_id if role == "assistant" else None)
                is_boundary = cursor.kind == "system" and cursor.parent is None
                if is_boundary:
                    boundaries.append(cursor)
                parent = cursor.parent or cursor.logical_parent
                nxt = index.nodes.get(parent) if parent else None
                if nxt is None and is_boundary and cursor.logical_parent and hops < MAX_FILE_HOPS:
                    holder = predecessor.find_holder(path, cursor.logical_parent)
                    if holder is not None:
                        hops += 1
                        path, index = holder, transcript_index.cached_index(holder)
                        stream = stack.enter_context(path.open("rb"))
                        nxt = index.nodes.get(cursor.logical_parent)
                if (nxt is None or nxt.uuid in seen) and boundaries:
                    nxt = _before_boundary(index, boundaries.pop(), seen)
                cursor = nxt
    except OSError as exc:
        raise TranscriptUnavailable(f"the transcript could not be read: {exc.strerror or exc}") from exc
    for part in found:
        text = str(part["text"])
        part["truncated"] = len(text) > PART_CHARS
        part["text"] = text[:PART_CHARS]
    found.reverse()
    return found


def bookmark_preview(bookmark_id: int, turns: Optional[int] = None) -> dict:
    mark = store.get_store().get(bookmark_id)
    used = clamp_turns(turns) if turns is not None else configured_turns()
    row = rows.read_row(mark.session_uuid)
    path = locate.find_transcript(mark.claude_session_uuid, row.working_dir)
    return {"bookmark_id": mark.id, "conversation": mark.claude_session_uuid, "turns": used,
            "parts": preview_parts(path, mark.entry_uuid, used)}


def compaction_preview(session_uuid: str, entry_uuid: str, turns: Optional[int] = None) -> dict:
    row = rows.read_row(session_uuid)
    points = compactions.list_compactions(row.claude_session_uuid, row.working_dir)
    if not any(point["entry_uuid"] == entry_uuid for point in points):
        raise EntryNotFound("that is not a compaction point of this session")
    used = clamp_turns(turns) if turns is not None else configured_turns()
    path = locate.find_transcript(row.claude_session_uuid, row.working_dir)
    return {"entry_uuid": entry_uuid, "conversation": row.claude_session_uuid, "turns": used,
            "parts": preview_parts(path, entry_uuid, used)}
