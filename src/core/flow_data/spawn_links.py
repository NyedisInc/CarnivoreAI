
from __future__ import annotations

import sqlite3
import time
from contextlib import closing, contextmanager
from typing import Any, Dict, Iterator, List, Optional

import structlog

from src.core.db import DatastoreError, transaction
from src.core.flow_data import main_db

logger = structlog.get_logger()

MAX_CHILDREN = 200
KIND_SESSION = "session"
KIND_EXTERNAL = "external"


def _stamp_session_row(conn: sqlite3.Connection, parent_row_id: int, child_row_id: int, child_uuid: Optional[str]) -> None:
    from src.core.db_models import SESSION_FORK_KIND_SPAWN
    from src.core.lineage import constants as LK
    from src.core.lineage import graph
    from src.core.trail_entry import utc_now

    stamp = utc_now()
    conn.execute("UPDATE sessions SET parent_session_id = ?, fork_kind = ?, updated_at = ? WHERE id = ? AND parent_session_id IS NULL",
                 (parent_row_id, SESSION_FORK_KIND_SPAWN, stamp, child_row_id))
    parent = conn.execute("SELECT session_uuid FROM sessions WHERE id = ?", (parent_row_id,)).fetchone()
    if child_uuid and parent is not None and parent[0] and graph.ready(conn):
        graph.add_edge(conn, LK.NODE_SESSION, parent[0], LK.NODE_SESSION, child_uuid, LK.KIND_SPAWNED_BY, created_at=stamp,
                       detail={"via": "agent_spawn"})


def record_spawn(*, child_id: str, child_uuid: Optional[str], parent_id: str, parent_uuid: Optional[str],
                 parent_kind: str, task_message_id: Optional[str], peer_install_id: Optional[str] = None,
                 at: Optional[float] = None, parent_row_id: Optional[int] = None, child_row_id: Optional[int] = None) -> bool:
    with closing(main_db.open_main()) as conn, transaction(conn):
        cur = conn.execute(
            "INSERT OR IGNORE INTO agent_spawn_links (child_id, child_uuid, parent_id, parent_uuid, parent_kind, "
            "task_message_id, peer_install_id, spawned_at) VALUES (?,?,?,?,?,?,?,?)",
            (child_id, child_uuid, parent_id, parent_uuid, parent_kind, task_message_id, peer_install_id,
             time.time() if at is None else at))
        if parent_row_id is not None and child_row_id is not None:
            _stamp_session_row(conn, parent_row_id, child_row_id, child_uuid)
        return cur.rowcount > 0


@contextmanager
def _reading(conn: Optional[sqlite3.Connection]) -> Iterator[sqlite3.Connection]:
    if conn is not None:
        yield conn
        return
    with closing(main_db.open_main()) as own:
        yield own


def _link(row: sqlite3.Row) -> Dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def parent_of(*, child_uuid: Optional[str] = None, child_id: Optional[str] = None,
              conn: Optional[sqlite3.Connection] = None) -> Optional[Dict[str, Any]]:
    with _reading(conn) as db:
        for column, value in (("child_uuid", child_uuid), ("child_id", child_id)):
            if value:
                row = db.execute(f"SELECT * FROM agent_spawn_links WHERE {column} = ?", (value,)).fetchone()
                if row is not None:
                    return _link(row)
    return None


def children_of(*, parent_uuid: Optional[str] = None, parent_id: Optional[str] = None,
                conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    clauses, params = [], []
    for column, value in (("parent_uuid", parent_uuid), ("parent_id", parent_id)):
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    if not clauses:
        return []
    with _reading(conn) as db:
        rows = db.execute(f"SELECT * FROM agent_spawn_links WHERE {' OR '.join(clauses)} "
                            f"ORDER BY spawned_at, child_id LIMIT {MAX_CHILDREN}", params).fetchall()
    return [_link(r) for r in rows]


def record_quietly(**kwargs: Any) -> None:
    try:
        record_spawn(**kwargs)
    except (sqlite3.Error, OSError, DatastoreError) as exc:
        logger.warning("spawn_link_record_failed", child_id=kwargs.get("child_id"), error_type=type(exc).__name__, error=str(exc))
