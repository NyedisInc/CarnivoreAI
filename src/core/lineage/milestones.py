
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional

from src.core.db import after_commit
from src.core.lineage import constants as K
from src.core.lineage.graph import LineageValueError, now_iso
from src.core.session_timeline import push as timeline_push


def add_milestone(conn: sqlite3.Connection, conversation_id: str, kind: str, source: str, *,
                  session_uuid: Optional[str] = None, at_ts: Optional[str] = None, jsonl_line: Optional[int] = None,
                  jsonl_offset: Optional[int] = None, detail: Optional[Dict[str, Any]] = None) -> bool:
    if kind not in K.MILESTONE_KINDS:
        raise LineageValueError(f"milestone kind {kind!r} is not one of {K.MILESTONE_KINDS}")
    if source not in K.MILESTONE_SOURCES:
        raise LineageValueError(f"milestone source {source!r} is not one of {K.MILESTONE_SOURCES}")
    stamp = now_iso()
    if at_ts is None and source == K.SOURCE_PIPELINE:
        at_ts = stamp
    cursor = conn.execute(
        f"INSERT OR IGNORE INTO {K.MILESTONES_TABLE} (conversation_id, session_uuid, kind, at_ts, jsonl_line, "
        "jsonl_offset, source, detail_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (conversation_id, session_uuid, kind, at_ts, jsonl_line, jsonl_offset, source,
         json.dumps(detail or {}, sort_keys=True), stamp))
    written = cursor.rowcount == 1
    if written:
        after_commit(conn, timeline_push.announce)
    return written


def milestones_of(conn: sqlite3.Connection, conversation_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute(f"SELECT kind, at_ts, session_uuid, jsonl_line, jsonl_offset, source, detail_json "
                        f"FROM {K.MILESTONES_TABLE} WHERE conversation_id = ? ORDER BY at_ts, id",
                        (conversation_id,)).fetchall()
    out = []
    for r in rows:
        try:
            detail = json.loads(r[6] or "{}")
        except ValueError:
            detail = {}
        out.append({"kind": r[0], "at": r[1], "session_uuid": r[2], "jsonl_line": r[3], "jsonl_offset": r[4],
                    "source": r[5], "detail": detail})
    return out
