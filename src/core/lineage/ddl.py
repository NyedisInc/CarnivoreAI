
from __future__ import annotations

import sqlite3
from typing import Tuple

from src.core.lineage import constants as K

_TYPES = ", ".join(f"'{t}'" for t in K.NODE_TYPES)

DDL_EDGES = f"""
CREATE TABLE IF NOT EXISTS {K.EDGES_TABLE} (
  parent_type  TEXT NOT NULL CHECK (parent_type IN ({_TYPES})),
  parent_id    TEXT NOT NULL,
  child_type   TEXT NOT NULL CHECK (child_type IN ({_TYPES})),
  child_id     TEXT NOT NULL,
  edge_kind    TEXT NOT NULL,
  link_basis   TEXT NOT NULL DEFAULT '{K.BASIS_RECORDED}',
  detail_json  TEXT NOT NULL DEFAULT '{{}}',
  created_at   TEXT NOT NULL,
  PRIMARY KEY (parent_type, parent_id, child_type, child_id, edge_kind)
) WITHOUT ROWID
"""

_LEVELS = ", ".join(f"'{lv}'" for lv in K.NODE_LEVELS)

DDL_NODES = f"""
CREATE TABLE IF NOT EXISTS {K.NODES_TABLE} (
  node_type    TEXT NOT NULL CHECK (node_type IN ({_TYPES})),
  node_id      TEXT NOT NULL,
  level        TEXT CHECK (level IS NULL OR level IN ({_LEVELS})),
  entrypoint   TEXT,
  updated_at   TEXT NOT NULL,
  PRIMARY KEY (node_type, node_id)
) WITHOUT ROWID
"""

DDL_SOURCES = f"""
CREATE TABLE IF NOT EXISTS {K.SOURCES_TABLE} (
  transcript_id   INTEGER PRIMARY KEY,
  content_sha256  TEXT NOT NULL,
  extracted_at    TEXT NOT NULL
)
"""

DDL_MILESTONES = f"""
CREATE TABLE IF NOT EXISTS {K.MILESTONES_TABLE} (
  id               INTEGER PRIMARY KEY,
  conversation_id  TEXT NOT NULL,
  session_uuid     TEXT,
  kind             TEXT NOT NULL,
  at_ts            TEXT,
  jsonl_line       INTEGER,
  jsonl_offset     INTEGER,
  source           TEXT NOT NULL,
  detail_json      TEXT NOT NULL DEFAULT '{{}}',
  created_at       TEXT NOT NULL
)
"""

DDL_INDEXES: Tuple[str, ...] = (
    f"CREATE INDEX IF NOT EXISTS ix_lineage_edges_child ON {K.EDGES_TABLE} (child_type, child_id)",
    f"CREATE INDEX IF NOT EXISTS ix_lineage_nodes_level ON {K.NODES_TABLE} (level)",
    f"CREATE INDEX IF NOT EXISTS ix_conversation_milestones_conversation ON {K.MILESTONES_TABLE} (conversation_id, at_ts)",
    f"CREATE INDEX IF NOT EXISTS ix_conversation_milestones_kind ON {K.MILESTONES_TABLE} (kind, at_ts)",
    f"CREATE UNIQUE INDEX IF NOT EXISTS ux_conversation_milestones_line ON {K.MILESTONES_TABLE} "
    "(conversation_id, kind, jsonl_line) WHERE jsonl_line IS NOT NULL",
    f"CREATE UNIQUE INDEX IF NOT EXISTS ux_conversation_milestones_backfill ON {K.MILESTONES_TABLE} "
    f"(conversation_id, kind, COALESCE(session_uuid, '')) WHERE source = '{K.SOURCE_BACKFILL}'",
)

DDL_V49: Tuple[str, ...] = (DDL_EDGES, DDL_NODES, DDL_SOURCES, DDL_MILESTONES, *DDL_INDEXES)

REVERSAL_SQL_V49: Tuple[str, ...] = (
    f"DROP TABLE IF EXISTS {K.MILESTONES_TABLE}",
    f"DROP TABLE IF EXISTS {K.SOURCES_TABLE}",
    f"DROP TABLE IF EXISTS {K.NODES_TABLE}",
    f"DROP TABLE IF EXISTS {K.EDGES_TABLE}",
)

RETIRED_OBJECTS: Tuple[str, ...] = ("ix_conversation_index_parent", "conversation_index.link_basis")

_INDEX = "conversation_index"
_LINK_REASONS = ", ".join(f"'{r}'" for r in K.EDGE_KIND_BY_REASON if K.EDGE_KIND_BY_REASON[r] == r)
_DROP_COLUMN_MIN = (3, 35, 0)


def _columns(conn: sqlite3.Connection, table: str) -> set:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _move_pointer_data(conn: sqlite3.Connection, cols: set) -> None:
    basis = f"COALESCE(ci.link_basis, '{K.BASIS_RECORDED}')" if "link_basis" in cols else f"'{K.BASIS_RECORDED}'"
    conn.execute(
        f"INSERT OR IGNORE INTO {K.EDGES_TABLE} (parent_type, parent_id, child_type, child_id, edge_kind, "
        f"link_basis, created_at) SELECT '{K.NODE_CONVERSATION}', ci.conversation_id, '{K.NODE_SESSION}', "
        f"ci.session_uuid, ci.ended_reason, {basis}, COALESCE(ci.ended_at, ci.captured_at) FROM {_INDEX} ci "
        f"WHERE ci.session_uuid IS NOT NULL AND ci.ended_reason IN ({_LINK_REASONS})")
    if "parent_conversation_id" in cols:
        parent_basis = (f"COALESCE(p.link_basis, '{K.BASIS_RECORDED}')" if "link_basis" in cols
                        else f"'{K.BASIS_RECORDED}'")
        for child_type, child_col in ((K.NODE_CONVERSATION, "ci.conversation_id"), (K.NODE_SESSION, "ci.session_uuid")):
            conn.execute(
                f"INSERT OR IGNORE INTO {K.EDGES_TABLE} (parent_type, parent_id, child_type, child_id, edge_kind, "
                f"link_basis, created_at) SELECT '{K.NODE_CONVERSATION}', ci.parent_conversation_id, '{child_type}', "
                f"{child_col}, CASE WHEN p.ended_reason IN ({_LINK_REASONS}) THEN p.ended_reason "
                f"ELSE '{K.KIND_SWITCH}' END, {parent_basis}, COALESCE(ci.started_at, ci.captured_at) "
                f"FROM {_INDEX} ci LEFT JOIN {_INDEX} p ON p.conversation_id = ci.parent_conversation_id "
                f"WHERE ci.parent_conversation_id IS NOT NULL AND {child_col} IS NOT NULL")
    detail = "json_object('origin', 'v49_migration'" + (", 'link_basis', ci.link_basis)" if "link_basis" in cols else ")")
    conn.execute(
        f"INSERT OR IGNORE INTO {K.MILESTONES_TABLE} (conversation_id, session_uuid, kind, at_ts, source, "
        f"detail_json, created_at) SELECT ci.conversation_id, ci.session_uuid, ci.ended_reason, ci.ended_at, "
        f"'{K.SOURCE_BACKFILL}', {detail}, ci.captured_at FROM {_INDEX} ci WHERE ci.ended_reason IS NOT NULL")


def _drop_retired(conn: sqlite3.Connection, cols: set) -> None:
    if sqlite3.sqlite_version_info < _DROP_COLUMN_MIN:
        return
    conn.execute("DROP INDEX IF EXISTS ix_conversation_index_parent")
    for column in ("parent_conversation_id", "link_basis"):
        if column in cols:
            conn.execute(f"ALTER TABLE {_INDEX} DROP COLUMN {column}")


def apply_v49(conn: sqlite3.Connection) -> None:
    for statement in DDL_V49:
        conn.execute(statement)
    cols = _columns(conn, _INDEX)
    if not cols:
        return
    _move_pointer_data(conn, cols)
    _drop_retired(conn, cols)
