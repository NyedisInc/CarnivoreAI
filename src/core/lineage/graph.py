
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from src.core.db import after_commit
from src.core.lineage import constants as K
from src.core.session_timeline import push as timeline_push


class LineageValueError(ValueError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ready(conn: sqlite3.Connection) -> bool:
    found = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (K.EDGES_TABLE,)).fetchone()
    return found is not None


def _check(parent_type: str, child_type: str, kind: str, basis: str) -> None:
    if parent_type not in K.NODE_TYPES or child_type not in K.NODE_TYPES:
        raise LineageValueError(f"node type must be one of {K.NODE_TYPES}")
    if kind not in K.EDGE_KINDS:
        raise LineageValueError(f"edge kind {kind!r} is not one of {K.EDGE_KINDS}")
    if basis not in K.LINK_BASES:
        raise LineageValueError(f"link basis {basis!r} is not one of {K.LINK_BASES}")


def _merged(stored: Optional[str], extra: Optional[Dict[str, Any]]) -> Optional[str]:
    if not extra:
        return None
    try:
        base = json.loads(stored or "{}")
    except ValueError:
        base = {}
    if not isinstance(base, dict):
        base = {}
    merged = {**base, **{k: v for k, v in extra.items() if v is not None}}
    return None if merged == base else json.dumps(merged, sort_keys=True)


def add_edge(conn: sqlite3.Connection, parent_type: str, parent_id: str, child_type: str, child_id: str, kind: str,
             *, basis: str = K.BASIS_RECORDED, created_at: Optional[str] = None,
             detail: Optional[Dict[str, Any]] = None) -> str:
    _check(parent_type, child_type, kind, basis)
    key = (parent_type, parent_id, child_type, child_id, kind)
    where = "WHERE parent_type = ? AND parent_id = ? AND child_type = ? AND child_id = ? AND edge_kind = ?"
    row = conn.execute(f"SELECT link_basis, detail_json FROM {K.EDGES_TABLE} {where}", key).fetchone()
    if row is None:
        conn.execute(f"INSERT INTO {K.EDGES_TABLE} (parent_type, parent_id, child_type, child_id, edge_kind, "
                     "link_basis, detail_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (*key, basis, json.dumps(detail or {}, sort_keys=True), created_at or now_iso()))
        after_commit(conn, timeline_push.announce)
        return "added"
    outcome = "present"
    merged = _merged(row[1], detail)
    if merged is not None:
        conn.execute(f"UPDATE {K.EDGES_TABLE} SET detail_json = ? {where}", (merged, *key))
        outcome = "detailed"
    if basis == K.BASIS_RECORDED and row[0] != K.BASIS_RECORDED:
        conn.execute(f"UPDATE {K.EDGES_TABLE} SET link_basis = ? {where}", (basis, *key))
        outcome = "upgraded"
    if outcome != "present":
        after_commit(conn, timeline_push.announce)
    return outcome


def retype_edge(conn: sqlite3.Connection, parent_type: str, parent_id: str, child_type: str, child_id: str,
                old_kind: str, new_kind: str, *, detail: Optional[Dict[str, Any]] = None) -> bool:
    _check(parent_type, child_type, new_kind, K.BASIS_RECORDED)
    where = "WHERE parent_type = ? AND parent_id = ? AND child_type = ? AND child_id = ? AND edge_kind = ?"
    old = conn.execute(f"SELECT detail_json, created_at FROM {K.EDGES_TABLE} {where}",
                       (parent_type, parent_id, child_type, child_id, old_kind)).fetchone()
    if old is None:
        return False
    try:
        carried = json.loads(old[0] or "{}")
    except ValueError:
        carried = {}
    add_edge(conn, parent_type, parent_id, child_type, child_id, new_kind, basis=K.BASIS_RECORDED,
             created_at=old[1], detail={**(carried if isinstance(carried, dict) else {}), **(detail or {})})
    conn.execute(f"DELETE FROM {K.EDGES_TABLE} {where}", (parent_type, parent_id, child_type, child_id, old_kind))
    return True


_EDGE_COLUMNS = ("parent_type", "parent_id", "child_type", "child_id", "edge_kind", "link_basis", "created_at",
                 "detail_json")
_SELECT = f"SELECT {', '.join(_EDGE_COLUMNS)} FROM {K.EDGES_TABLE}"


def _edge(row: Sequence[Any]) -> Dict[str, Any]:
    edge = dict(zip(_EDGE_COLUMNS, tuple(row)))
    try:
        edge["detail"] = json.loads(edge.pop("detail_json") or "{}")
    except ValueError:
        edge["detail"] = {}
    return edge


def _kinds_clause(kinds: Optional[Sequence[str]]) -> tuple:
    if not kinds:
        return "", ()
    return f" AND edge_kind IN ({','.join('?' for _ in kinds)})", tuple(kinds)


def parents_of(conn: sqlite3.Connection, node_type: str, node_id: str,
               kinds: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    extra, params = _kinds_clause(kinds)
    rows = conn.execute(f"{_SELECT} WHERE child_type = ? AND child_id = ?{extra} "
                        "ORDER BY created_at DESC, child_id, parent_id", (node_type, node_id, *params)).fetchall()
    return [_edge(r) for r in rows]


def children_of(conn: sqlite3.Connection, node_type: str, node_id: str,
                kinds: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    extra, params = _kinds_clause(kinds)
    rows = conn.execute(f"{_SELECT} WHERE parent_type = ? AND parent_id = ?{extra} "
                        "ORDER BY created_at DESC, child_id, parent_id", (node_type, node_id, *params)).fetchall()
    return [_edge(r) for r in rows]


def siblings_of(conn: sqlite3.Connection, node_type: str, node_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        f"SELECT o.child_type, o.child_id, o.parent_type, o.parent_id, o.edge_kind, o.link_basis "
        f"FROM {K.EDGES_TABLE} mine JOIN {K.EDGES_TABLE} o ON o.parent_type = mine.parent_type "
        "AND o.parent_id = mine.parent_id AND o.edge_kind = mine.edge_kind AND o.child_type = mine.child_type "
        "WHERE mine.child_type = ? AND mine.child_id = ? AND o.child_id != mine.child_id AND mine.edge_kind != ? "
        "ORDER BY o.created_at DESC, o.child_id", (node_type, node_id, K.KIND_SUBAGENT)).fetchall()
    return [{"node_type": r[0], "node_id": r[1], "via_parent_type": r[2], "via_parent_id": r[3],
             "edge_kind": r[4], "link_basis": r[5]} for r in rows]


def previous_conversations(conn: sqlite3.Connection, session_uuid: str,
                           current_id: Optional[str] = None) -> List[Dict[str, Any]]:
    edges = parents_of(conn, K.NODE_SESSION, session_uuid, K.CONTINUATION_KINDS)
    seen, out = set(), []
    for edge in edges:
        if edge["parent_type"] != K.NODE_CONVERSATION or edge["parent_id"] == current_id or edge["parent_id"] in seen:
            continue
        seen.add(edge["parent_id"])
        out.append(edge)
    return out


def previous_counts(conn: sqlite3.Connection) -> Dict[str, int]:
    if not ready(conn):
        return {}
    marks = ",".join("?" for _ in K.CONTINUATION_KINDS)
    rows = conn.execute(
        f"SELECT e.child_id AS session_uuid, COUNT(DISTINCT e.parent_id) AS n FROM {K.EDGES_TABLE} e "
        "JOIN sessions s ON s.session_uuid = e.child_id "
        f"WHERE e.child_type = ? AND e.parent_type = ? AND e.edge_kind IN ({marks}) "
        "AND e.parent_id != COALESCE(s.claude_session_uuid, '') GROUP BY e.child_id",
        (K.NODE_SESSION, K.NODE_CONVERSATION, *K.CONTINUATION_KINDS)).fetchall()
    return {r[0]: int(r[1]) for r in rows}


def set_node(conn: sqlite3.Connection, node_type: str, node_id: str, level: Optional[str],
             entrypoint: Optional[str] = None) -> bool:
    if node_type not in K.NODE_TYPES or (level is not None and level not in K.NODE_LEVELS):
        raise LineageValueError(f"node type must be one of {K.NODE_TYPES}, level one of {K.NODE_LEVELS}")
    before = conn.total_changes
    conn.execute(
        f"INSERT INTO {K.NODES_TABLE} (node_type, node_id, level, entrypoint, updated_at) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(node_type, node_id) DO UPDATE SET level = COALESCE(excluded.level, level), "
        "entrypoint = COALESCE(excluded.entrypoint, entrypoint), updated_at = excluded.updated_at "
        "WHERE COALESCE(excluded.level, level) IS NOT level OR COALESCE(excluded.entrypoint, entrypoint) IS NOT entrypoint",
        (node_type, node_id, level, entrypoint, now_iso()))
    return conn.total_changes > before


def levels_of(conn: sqlite3.Connection, nodes: Sequence[tuple]) -> Dict[str, Optional[str]]:
    out: Dict[str, Optional[str]] = {}
    for node_type, node_id in nodes:
        row = conn.execute(f"SELECT level FROM {K.NODES_TABLE} WHERE node_type = ? AND node_id = ?",
                           (node_type, node_id)).fetchone()
        level = row[0] if row is not None else None
        if level is None and node_type == K.NODE_SUBAGENT:
            level = K.LEVEL_AGENT
        if level is None and node_type == K.NODE_SESSION:
            level = K.LEVEL_HUMAN
        out[f"{node_type}:{node_id}"] = level
    return out
