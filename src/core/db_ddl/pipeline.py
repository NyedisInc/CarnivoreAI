
from __future__ import annotations

import sqlite3
from typing import Tuple

from src.core.db_ddl import tables as K

DDL_JOBS = f"""
CREATE TABLE IF NOT EXISTS {K.JOBS_TABLE} (
  id                     INTEGER PRIMARY KEY,
  conversation_id        TEXT NOT NULL,
  session_uuid           TEXT,
  event                  TEXT NOT NULL,
  agent_family           TEXT NOT NULL DEFAULT 'claude',
  child_conversation_id  TEXT,
  label                  TEXT,
  comment                TEXT,
  priority               INTEGER NOT NULL DEFAULT 0,
  dedupe_key             TEXT NOT NULL,
  state                  TEXT NOT NULL DEFAULT 'queued'
                         CHECK (state IN ('queued', 'running', 'failed', 'done', 'dead', 'cancelled')),
  capture_scope          TEXT,
  record_lineage         INTEGER NOT NULL DEFAULT 1,
  options_json           TEXT NOT NULL DEFAULT '{{}}',
  point_id               TEXT,
  capture_status         TEXT,
  created_at             TEXT NOT NULL,
  updated_at             TEXT NOT NULL,
  finished_at            TEXT
)
"""

DDL_STAGES = f"""
CREATE TABLE IF NOT EXISTS {K.STAGES_TABLE} (
  job_id       INTEGER NOT NULL REFERENCES {K.JOBS_TABLE}(id) ON DELETE CASCADE,
  stage        TEXT NOT NULL,
  seq          INTEGER NOT NULL,
  status       TEXT NOT NULL DEFAULT 'pending'
               CHECK (status IN ('pending', 'running', 'done', 'skipped', 'failed', 'dead')),
  attempts     INTEGER NOT NULL DEFAULT 0,
  last_error   TEXT,
  next_try_at  REAL,
  lease_until  REAL,
  started_at   TEXT,
  finished_at  TEXT,
  output_json  TEXT NOT NULL DEFAULT '{{}}',
  PRIMARY KEY (job_id, stage)
)
"""

DDL_INDEXES: Tuple[str, ...] = (
    f"CREATE UNIQUE INDEX IF NOT EXISTS ux_pipeline_jobs_open_dedupe ON {K.JOBS_TABLE} (dedupe_key) "
    "WHERE state NOT IN ('done', 'dead', 'cancelled')",
    f"CREATE INDEX IF NOT EXISTS ix_pipeline_jobs_state ON {K.JOBS_TABLE} (state, priority, created_at)",
    f"CREATE INDEX IF NOT EXISTS ix_pipeline_jobs_conversation ON {K.JOBS_TABLE} (conversation_id, id)",
    f"CREATE INDEX IF NOT EXISTS ix_pipeline_stage_runs_status ON {K.STAGES_TABLE} (status, next_try_at)",
)

DDL_V51: Tuple[str, ...] = (DDL_JOBS, DDL_STAGES, *DDL_INDEXES)

REVERSAL_SQL_V51: Tuple[str, ...] = (f"DROP TABLE IF EXISTS {K.STAGES_TABLE}", f"DROP TABLE IF EXISTS {K.JOBS_TABLE}")


def apply_v51(conn: sqlite3.Connection) -> None:
    for statement in DDL_V51:
        conn.execute(statement)


V53_SERVER_COLUMN = "server"
V53_WAIT_COLUMN = "wait_reason"
DDL_V53_ADD_SERVER = f"ALTER TABLE {K.STAGES_TABLE} ADD COLUMN {V53_SERVER_COLUMN} TEXT"
DDL_V53_ADD_WAIT = f"ALTER TABLE {K.STAGES_TABLE} ADD COLUMN {V53_WAIT_COLUMN} TEXT"

V53_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    (K.STAGES_TABLE, V53_SERVER_COLUMN, DDL_V53_ADD_SERVER),
    (K.STAGES_TABLE, V53_WAIT_COLUMN, DDL_V53_ADD_WAIT),
)

REVERSAL_SQL_V53: Tuple[str, ...] = ()


def apply_v53(conn: sqlite3.Connection) -> None:
    present = {row[1] for row in conn.execute(f"PRAGMA table_info({K.STAGES_TABLE})")}
    for _table, column, statement in V53_COLUMNS:
        if present and column not in present:
            conn.execute(statement)
