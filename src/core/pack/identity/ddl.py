
from __future__ import annotations

import sqlite3
import uuid
from typing import Tuple

PACK_STATES: Tuple[str, ...] = ("home", "replica", "moved_away")
TRANSPORT_RUNGS: Tuple[str, ...] = ("git", "carried", "tar")

_UID_SQL = (
    "(SELECT substr(h, 1, 12) || '4' || substr(h, 14, 3) || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(h, 18, 15) "
    "FROM (SELECT lower(hex(randomblob(16))) AS h))"
)

V80_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    ("projects", "uid", "ALTER TABLE projects ADD COLUMN uid TEXT"),
    ("projects", "home_install_id", "ALTER TABLE projects ADD COLUMN home_install_id TEXT"),
    ("projects", "pack_state",
     "ALTER TABLE projects ADD COLUMN pack_state TEXT NOT NULL DEFAULT 'home' CHECK (pack_state IN ('home','replica','moved_away'))"),
    ("projects", "moved_to_install_id", "ALTER TABLE projects ADD COLUMN moved_to_install_id TEXT"),
    ("projects", "air_gap", "ALTER TABLE projects ADD COLUMN air_gap INTEGER NOT NULL DEFAULT 0"),
    ("projects", "github_account", "ALTER TABLE projects ADD COLUMN github_account TEXT"),
    ("companies", "uid", "ALTER TABLE companies ADD COLUMN uid TEXT"),
)

DDL_V80: Tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_projects_uid ON projects(uid)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_companies_uid ON companies(uid)",
    """CREATE TABLE IF NOT EXISTS project_replicas (
        project_uid    TEXT NOT NULL,
        install_id     TEXT NOT NULL,
        root           TEXT,
        transport_rung TEXT NOT NULL DEFAULT 'git' CHECK (transport_rung IN ('git','carried','tar')),
        state          TEXT NOT NULL DEFAULT 'active',
        created_at     TEXT NOT NULL,
        updated_at     TEXT NOT NULL,
        PRIMARY KEY (project_uid, install_id)
    )""",
)

TRIGGERS: Tuple[str, ...] = tuple(
    f"CREATE TRIGGER IF NOT EXISTS trg_{table}_uid AFTER INSERT ON {table} WHEN NEW.uid IS NULL "
    f"BEGIN UPDATE {table} SET uid = {_UID_SQL} WHERE id = NEW.id; END"
    for table in ("projects", "companies")
)


def backfill_uids(conn: sqlite3.Connection) -> int:
    filled = 0
    for table in ("projects", "companies"):
        for (row_id,) in conn.execute(f"SELECT id FROM {table} WHERE uid IS NULL").fetchall():
            conn.execute(f"UPDATE {table} SET uid = ? WHERE id = ?", (uuid.uuid4().hex, row_id))
            filled += 1
    return filled


def apply_v80(conn: sqlite3.Connection) -> None:
    for table, column, statement in V80_COLUMNS:
        present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if present and column not in present:
            conn.execute(statement)
    backfill_uids(conn)
    for statement in DDL_V80:
        conn.execute(statement)
    for statement in TRIGGERS:
        conn.execute(statement)
