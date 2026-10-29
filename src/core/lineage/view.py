
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

from src.core.lineage import constants as K
from src.core.lineage import graph


def _held_conversations(conn: sqlite3.Connection, session_uuid: str) -> Optional[List[str]]:
    """The conversations a session holds (current first), or None when no such session row exists."""
    row = conn.execute("SELECT claude_session_uuid FROM sessions WHERE session_uuid = ?", (session_uuid,)).fetchone()
    if row is None:
        return None
    current = row[0]
    held = [current] if current else []
    held += [e["parent_id"] for e in graph.previous_conversations(conn, session_uuid, current)]
    return held


def neighbourhood(conn: sqlite3.Connection, node_type: str, node_id: str) -> Optional[Dict[str, Any]]:
    """Everything linked to one node, or None for a session that does not exist.

    Inputs: conn; node_type (``session``, ``conversation`` or ``subagent``); node_id.
    Output: dict ``{node: {type, id}, levels, conversations, parents, children, siblings, subagents}``; ``conversations``
      is the session's held conversations (empty for another node type); edges keep their kind and basis.
    Raises: graph.LineageValueError for an unknown node type.
    Example: neighbourhood(conn, 'session', 's1')['siblings']
    """
    if node_type not in K.NODE_TYPES:
        raise graph.LineageValueError(f"node type must be one of {K.NODE_TYPES}")
    held: List[str] = []
    if node_type == K.NODE_SESSION:
        found = _held_conversations(conn, node_id)
        if found is None:
            return None
        held = found
    children = [e for e in graph.children_of(conn, node_type, node_id) if e["edge_kind"] != K.KIND_SUBAGENT]
    owners = held if node_type == K.NODE_SESSION else [node_id]
    subagents = [e for owner in owners for e in graph.children_of(conn, K.NODE_CONVERSATION, owner, (K.KIND_SUBAGENT,))]
    parents = graph.parents_of(conn, node_type, node_id)
    siblings = graph.siblings_of(conn, node_type, node_id)
    nodes = {(node_type, node_id)} | {(e["parent_type"], e["parent_id"]) for e in parents}
    nodes |= {(e["child_type"], e["child_id"]) for e in children + subagents}
    nodes |= {(s["node_type"], s["node_id"]) for s in siblings}
    return {
        "node": {"type": node_type, "id": node_id},
        "levels": graph.levels_of(conn, sorted(nodes)),
        "conversations": held,
        "parents": parents,
        "children": children,
        "siblings": siblings,
        "subagents": subagents,
    }
