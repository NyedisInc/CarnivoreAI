
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

from src.core.lineage import constants as K
from src.core.lineage import graph, milestones

_MILESTONE_DETAIL_KEYS = ("trigger", "pre_tokens", "label", "copy_conversation_id", "child_conversation_id")


def _began(conn: sqlite3.Connection, conversation_id: str) -> Optional[Dict[str, Any]]:
    edges = [e for e in graph.parents_of(conn, K.NODE_CONVERSATION, conversation_id, K.CONTINUATION_KINDS)
             if e["parent_type"] == K.NODE_CONVERSATION and e["parent_id"] != conversation_id]
    if not edges:
        return None
    edge = sorted(edges, key=lambda e: e["created_at"] or "")[0]
    detail = edge["detail"]
    split = None
    if detail.get(K.DETAIL_SPLIT_SESSION) or detail.get(K.DETAIL_SPLIT_MESSAGE):
        split = {"conversation": detail.get(K.DETAIL_SPLIT_SESSION), "message_uuid": detail.get(K.DETAIL_SPLIT_MESSAGE),
                 "line": detail.get(K.DETAIL_COPY_LINE)}
    return {"kind": edge["edge_kind"], "from_conversation": edge["parent_id"], "basis": edge["link_basis"],
            "at": edge["created_at"], "split": split}


def _marks(conn: sqlite3.Connection, conversation_id: str) -> List[Dict[str, Any]]:
    return [{"kind": m["kind"], "at": m["at"], "jsonl_line": m["jsonl_line"], "source": m["source"],
             **{k: m["detail"][k] for k in _MILESTONE_DETAIL_KEYS if k in m["detail"]}}
            for m in milestones.milestones_of(conn, conversation_id)]


def session_timeline(conn: sqlite3.Connection, session_uuid: str) -> Optional[List[Dict[str, Any]]]:
    row = conn.execute("SELECT claude_session_uuid FROM sessions WHERE session_uuid = ?", (session_uuid,)).fetchone()
    if row is None:
        return None
    current = row[0]
    left_at: Dict[str, str] = {}
    for edge in graph.previous_conversations(conn, session_uuid, current):
        left_at[edge["parent_id"]] = min(left_at.get(edge["parent_id"], edge["created_at"] or ""), edge["created_at"] or "")
    ordered = sorted(left_at, key=lambda conv: left_at[conv]) + ([current] if current else [])
    levels = graph.levels_of(conn, [(K.NODE_CONVERSATION, c) for c in ordered])
    return [{"conversation_id": conv, "current": conv == current,
             "level": levels.get(f"{K.NODE_CONVERSATION}:{conv}"), "began": _began(conn, conv),
             "milestones": _marks(conn, conv)} for conv in ordered]
