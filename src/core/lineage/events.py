
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.core.lineage import constants as K
from src.core.lineage import graph, milestones

logger = structlog.get_logger()


def record_flip_edges(conn: sqlite3.Connection, conversation_id: str, session_uuid: str, reason: str, *,
                      child_conversation_id: Optional[str] = None, basis: str = K.BASIS_RECORDED,
                      created_at: Optional[str] = None) -> int:
    kind = K.EDGE_KIND_BY_REASON.get(reason)
    if kind is None:
        return 0
    changed = 0
    targets = [(K.NODE_SESSION, session_uuid)]
    if child_conversation_id and child_conversation_id != conversation_id:
        targets.append((K.NODE_CONVERSATION, child_conversation_id))
    for child_type, child_id in targets:
        outcome = graph.add_edge(conn, K.NODE_CONVERSATION, conversation_id, child_type, child_id, kind,
                                 basis=basis, created_at=created_at)
        changed += outcome != "present"
    return changed


EVENT_WRITTEN = "written"
EVENT_PRESENT = "present"
EVENT_NOT_A_MILESTONE = "not_a_milestone"
EVENT_NO_SCHEMA = "no_schema"


def write_capture_event(db_path: Path, reason: str, conversation_id: str, session_uuid: Optional[str], *,
                        child_conversation_id: Optional[str] = None, point_id: Optional[str] = None,
                        capture_status: Optional[str] = None, at_ts: Optional[str] = None,
                        jsonl_offset: Optional[int] = None, extra_detail: Optional[Dict[str, Any]] = None) -> str:
    if reason not in K.MILESTONE_KINDS:
        return EVENT_NOT_A_MILESTONE
    from src.core.db import connect, transaction

    with closing(connect(db_path, create=False)) as conn:
        if not graph.ready(conn):
            logger.info("lineage_event_skipped", reason="datastore before schema v49", event=reason)
            return EVENT_NO_SCHEMA
        with transaction(conn):
            if at_ts is not None and conn.execute(
                    f"SELECT 1 FROM {K.MILESTONES_TABLE} WHERE conversation_id = ? AND kind = ? AND at_ts = ? "
                    "AND source = ?", (conversation_id, reason, at_ts, K.SOURCE_PIPELINE)).fetchone():
                return EVENT_PRESENT
            detail = {k: v for k, v in (("point_id", point_id), ("capture", capture_status),
                                        ("child_conversation_id", child_conversation_id)) if v}
            detail.update({k: v for k, v in (extra_detail or {}).items() if v is not None})
            milestones.add_milestone(conn, conversation_id, reason, K.SOURCE_PIPELINE,
                                     session_uuid=session_uuid, at_ts=at_ts, jsonl_offset=jsonl_offset,
                                     detail=detail)
            if session_uuid:
                record_flip_edges(conn, conversation_id, session_uuid, reason,
                                  child_conversation_id=child_conversation_id)
    if reason in (K.KIND_SWITCH, K.KIND_FORK):
        _settle_quietly(db_path, reason, child_conversation_id, session_uuid)
    return EVENT_WRITTEN


def _settle_quietly(db_path: Path, reason: str, child_conversation_id: Optional[str],
                    session_uuid: Optional[str]) -> None:
    from src.core.db import connect, transaction
    from src.core.lineage import reclassify, scan, split

    try:
        with closing(connect(db_path, create=False)) as conn, transaction(conn):
            if reason == K.KIND_SWITCH:
                reclassify.reclassify_switches(conn)
            path = scan.find_transcript(child_conversation_id, scan.roots()) if child_conversation_id else None
            if reason == K.KIND_FORK and path is not None:
                owners = {child_conversation_id: session_uuid} if session_uuid else None
                split.record_fork_pointer(conn, child_conversation_id, path, owners)
    except (sqlite3.Error, OSError) as exc:
        logger.warning("lineage_settle_failed", reason=reason, error=str(exc), error_type=type(exc).__name__)

