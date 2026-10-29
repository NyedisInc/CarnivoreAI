
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.lineage import graph
from src.core.session_conversations import classify
from src.core.session_transcript_presence import CONVERSATION_PRESENT, conversation_presence

MAX_PREVIOUS_SHOWN: int = 200


def index_ready(conn: sqlite3.Connection) -> bool:
    found = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'conversation_index'").fetchone()
    return found is not None


def conversation_ids(conn: sqlite3.Connection, session_uuid: str) -> set:
    """Every conversation id a session holds: the index rows it captured plus its lineage parents.

    Inputs: conn; session_uuid. Output: set of str (the current one may be absent from it).
    """
    found: set = set()
    if index_ready(conn):
        rows = conn.execute("SELECT conversation_id FROM conversation_index WHERE session_uuid = ?",
                            (session_uuid,)).fetchall()
        found |= {r["conversation_id"] for r in rows}
    if graph.ready(conn):
        found |= {e["parent_id"] for e in graph.previous_conversations(conn, session_uuid)}
    return found


def previous_counts(conn: sqlite3.Connection) -> Dict[str, int]:
    return graph.previous_counts(conn)


def _index_row(conn: sqlite3.Connection, conversation_id: str) -> Dict[str, Any]:
    if index_ready(conn):
        row = conn.execute("SELECT * FROM conversation_index WHERE conversation_id = ?", (conversation_id,)).fetchone()
        if row is not None:
            return dict(row)
    return {"conversation_id": conversation_id}


def _transcript_facts(path: Optional[Path], item: Dict[str, Any], *, current: bool) -> Dict[str, Any]:
    if path is None or (item.get("started_at") and item.get("first_prompt") and (current or item.get("ended_at"))):
        return item
    filled = dict(item)
    head = classify.read_head(path)
    filled["started_at"] = item.get("started_at") or head.started_at
    filled["first_prompt"] = item.get("first_prompt") or head.first_prompt
    if not current and not item.get("ended_at"):
        try:
            filled["ended_at"] = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except OSError:
            pass
    return filled


def _entry(conn: sqlite3.Connection, item: Dict[str, Any], *, current: bool,
           working_dir: Optional[str], corpus_root: Optional[Path],
           edge: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    conv = item["conversation_id"]
    presence = conversation_presence(conv, working_dir=working_dir, corpus_root=corpus_root)
    item = _transcript_facts(presence.path, item, current=current)
    return {
        "conversation_id": conv,
        "current": current,
        "started_at": item.get("started_at"),
        "ended_at": item.get("ended_at"),
        "ended_reason": edge["edge_kind"] if edge else item.get("ended_reason"),
        "link_basis": edge.get("link_basis") if edge else None,
        "first_prompt": item.get("first_prompt") or "",
        "summary": item.get("summary") or None,
        "transcript_on_disk": presence.outcome == CONVERSATION_PRESENT,
    }


def build(conn: sqlite3.Connection, session_uuid: str, *,
          corpus_root: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """The conversations of one session, or None when no such session row exists.

    Description: ``current`` is what the row points at now (built from its index row when there is one, a
      bare entry when it was never captured); ``previous`` is every conversation the session continued from
      (its lineage parents), newest first, each with the edge's kind as ``ended_reason`` and its ``link_basis``.
    Inputs: conn; session_uuid; corpus_root (transcript presence override).
    Output: dict {session_uuid, current, previous, previous_count} or None.
    Example: build(conn, 's')['previous'][0]['ended_reason']  # 'clear'
    """
    row = conn.execute("SELECT session_uuid, claude_session_uuid, working_dir FROM sessions WHERE session_uuid = ?",
                       (session_uuid,)).fetchone()
    if row is None:
        return None
    working_dir = row["working_dir"]
    current_id = row["claude_session_uuid"]
    current = None
    if current_id:
        current = _entry(conn, _index_row(conn, current_id), current=True, working_dir=working_dir,
                         corpus_root=corpus_root)
    ended = graph.previous_conversations(conn, session_uuid, current_id) if graph.ready(conn) else []
    previous = [_entry(conn, _index_row(conn, e["parent_id"]), current=False, working_dir=working_dir,
                       corpus_root=corpus_root, edge=e) for e in ended[:MAX_PREVIOUS_SHOWN]]
    return {"session_uuid": session_uuid, "current": current, "previous": previous, "previous_count": len(ended)}


def latest_lines(conn: sqlite3.Connection) -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}
    if index_ready(conn):
        rows = conn.execute("SELECT session_uuid, first_prompt, COALESCE(started_at, captured_at) AS at "
                            "FROM conversation_index WHERE session_uuid IS NOT NULL AND first_prompt != '' "
                            "ORDER BY COALESCE(started_at, captured_at) ASC").fetchall()
        for r in rows:
            out[r["session_uuid"]] = {"text": r["first_prompt"], "at": r["at"], "kind": "first_prompt"}
    return out
