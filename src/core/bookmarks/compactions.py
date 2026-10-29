
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.core.bookmarks import locate, rows, transcript_index
from src.core.bookmarks.errors import BookmarkError, TranscriptUnavailable
from src.core.lineage import constants as LK
from src.core.lineage import milestones

logger = structlog.get_logger()


def _boundary_by_line(path: Path, line: Optional[int]) -> Optional[str]:
    if not isinstance(line, int) or line < 1:
        return None
    try:
        with path.open("rb") as stream:
            for number, raw in enumerate(stream, start=1):
                if number < line:
                    continue
                record = json.loads(raw)
                if isinstance(record, dict) and record.get("type") == "system" \
                        and record.get("subtype") == "compact_boundary" and isinstance(record.get("uuid"), str):
                    return record["uuid"]
                return None
    except (OSError, ValueError) as exc:
        logger.debug("compaction_boundary_line_unreadable", path=str(path), line=line, error=str(exc))
    return None


def _boundary_by_offset(conversation: str, working_dir: Optional[str], offset: Optional[int],
                        line: Optional[int] = None) -> Optional[str]:
    if offset is None and line is None:
        return None
    try:
        path = locate.find_transcript(conversation, working_dir)
        index = transcript_index.cached_index(path) if offset is not None else None
    except TranscriptUnavailable as exc:
        logger.debug("compaction_boundary_unresolved", conversation=conversation, error=str(exc))
        return None
    if index is not None:
        for node in index.nodes.values():
            if node.offset == offset and node.kind == "system" and node.logical_parent:
                return node.uuid
    return _boundary_by_line(path, line)


def _point(m: Dict[str, Any], conversation: str, working_dir: Optional[str]) -> Dict[str, Any]:
    detail = m["detail"] if isinstance(m["detail"], dict) else {}
    uuid = detail.get("record_uuid") or _boundary_by_offset(conversation, working_dir, m["jsonl_offset"], m["jsonl_line"])
    return {"entry_uuid": uuid if isinstance(uuid, str) else None, "conversation": conversation,
            "at": m["at"] or "", "trigger": str(detail.get("trigger") or ""),
            "pre_tokens": detail.get("pre_tokens") if isinstance(detail.get("pre_tokens"), int) else None,
            "jsonl_line": m["jsonl_line"]}


def list_compactions(conversation: Optional[str], working_dir: Optional[str] = None,
                     path: Optional[Path] = None) -> List[Dict[str, Any]]:
    from src.core.db import DatastoreUnreadableError, connect

    if not conversation:
        return []
    try:
        with closing(connect(path or rows.db_path(), create=False)) as conn:
            found = [m for m in milestones.milestones_of(conn, conversation) if m["kind"] == LK.MILESTONE_COMPACT]
    except (DatastoreUnreadableError, sqlite3.Error) as exc:
        logger.debug("compactions_unreadable", conversation=conversation, error=str(exc))
        return []
    return [_point(m, conversation, working_dir) for m in reversed(found)]


def list_all_compactions(limit: int, path: Optional[Path] = None) -> List[Dict[str, Any]]:
    from src.core.db import DatastoreUnreadableError, connect

    sql = ("SELECT s.id, s.session_uuid, s.claude_session_uuid, s.working_dir, s.title, s.tmux_name, s.agent_type, "
           "m.at_ts AS at_ts, m.jsonl_line AS jsonl_line, m.jsonl_offset AS jsonl_offset, m.detail_json AS detail_json "
           f"FROM {LK.MILESTONES_TABLE} m JOIN sessions s ON s.claude_session_uuid = m.conversation_id "
           "WHERE m.kind = ? {host} ORDER BY m.at_ts DESC, m.id DESC LIMIT ?")
    try:
        with closing(connect(path or rows.db_path(), create=False)) as conn:
            try:
                found = conn.execute(sql.format(host="AND COALESCE(s.host_key, 'local') = 'local'"),
                                     (LK.MILESTONE_COMPACT, int(limit))).fetchall()
            except sqlite3.OperationalError as exc:
                if "no such column" not in str(exc):
                    raise
                found = conn.execute(sql.format(host=""), (LK.MILESTONE_COMPACT, int(limit))).fetchall()
    except (DatastoreUnreadableError, sqlite3.Error) as exc:
        logger.debug("all_compactions_unreadable", error=str(exc))
        return []
    families: Dict[Optional[str], str] = {}
    out = []
    for r in found:
        if r["agent_type"] not in families:
            families[r["agent_type"]] = rows.family_of(r["agent_type"])
        if families[r["agent_type"]] != "claude":
            continue
        try:
            detail = json.loads(r["detail_json"] or "{}")
        except ValueError:
            detail = {}
        milestone = {"at": r["at_ts"], "jsonl_line": r["jsonl_line"], "jsonl_offset": r["jsonl_offset"], "detail": detail}
        out.append({**_point(milestone, r["claude_session_uuid"], r["working_dir"]),
                    "session_uuid": r["session_uuid"], "session_row_id": r["id"],
                    "session_label": r["title"] or r["tmux_name"] or "", "session_tmux": r["tmux_name"] or "",
                    "family": "claude"})
    return out


def announce(session_uuid: Optional[str]) -> None:
    from src.core import resource_push
    from src.core.resource_push import topics

    if not session_uuid:
        return
    try:
        row = rows.read_row(session_uuid)
    except BookmarkError as exc:
        logger.debug("compaction_announce_skipped", session_uuid=session_uuid, error=str(exc))
        return
    resource_push.notify(topics.keyed(topics.BOOKMARKS, str(row.id)))
    resource_push.notify(topics.keyed(topics.BOOKMARKS, topics.ALL_KEY))
