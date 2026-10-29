
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from src.core.lineage import constants as K
from src.core.lineage import graph


@dataclass(frozen=True)
class SplitPoint:

    parent_conversation: str
    message_uuid: Optional[str]
    line: int


def read_split_point(path: Path) -> Optional[SplitPoint]:
    with path.open("rb") as handle:
        blob = handle.read(K.HEAD_BYTES)
    for number, raw in enumerate(blob.split(b"\n")[: K.HEAD_RECORDS], start=1):
        try:
            record = json.loads(raw)
        except ValueError:
            continue
        pointer = record.get("forkedFrom") if isinstance(record, dict) else None
        if isinstance(pointer, dict) and isinstance(pointer.get("sessionId"), str):
            message = pointer.get("messageUuid")
            return SplitPoint(pointer["sessionId"], message if isinstance(message, str) else None, number)
    return None


def split_detail(path: Path) -> Dict[str, object]:
    point = read_split_point(path)
    if point is None:
        return {}
    return {K.DETAIL_SPLIT_SESSION: point.parent_conversation, K.DETAIL_SPLIT_MESSAGE: point.message_uuid,
            K.DETAIL_COPY_LINE: point.line}


def record_fork_pointer(conn: sqlite3.Connection, conversation_id: str, path: Path,
                        session_of: Optional[Dict[str, str]] = None) -> bool:
    point = read_split_point(path)
    if point is None or point.parent_conversation == conversation_id:
        return False
    detail = {**split_detail(path), K.DETAIL_EVIDENCE: K.EVIDENCE_FORKED_FROM}
    graph.add_edge(conn, K.NODE_CONVERSATION, point.parent_conversation, K.NODE_CONVERSATION, conversation_id,
                   K.KIND_FORK, detail=detail)
    session = (session_of or {}).get(conversation_id)
    if session:
        graph.add_edge(conn, K.NODE_CONVERSATION, point.parent_conversation, K.NODE_SESSION, session, K.KIND_FORK,
                       detail=detail)
    return True
