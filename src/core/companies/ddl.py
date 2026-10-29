
from __future__ import annotations

import sqlite3
from typing import Tuple

COMPANY_COLUMN = "company_id"

DDL_V58: Tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS companies (
        id          INTEGER PRIMARY KEY,
        name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    )""",
)

DDL_PROJECTS_COMPANY_COLUMN = (
    f"ALTER TABLE projects ADD COLUMN {COMPANY_COLUMN} INTEGER REFERENCES companies(id) ON DELETE SET NULL"
)

V58_COLUMNS: Tuple[Tuple[str, str, str], ...] = (("projects", COMPANY_COLUMN, DDL_PROJECTS_COMPANY_COLUMN),)

DDL_PROJECTS_COMPANY_INDEX = "CREATE INDEX IF NOT EXISTS ix_projects_company ON projects(company_id)"


def apply_v58(conn: sqlite3.Connection) -> None:
    for statement in DDL_V58:
        conn.execute(statement)
    for table, column, statement in V58_COLUMNS:
        present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if present and column not in present:
            conn.execute(statement)
    present = {row[1] for row in conn.execute("PRAGMA table_info(projects)")}
    if COMPANY_COLUMN in present:
        conn.execute(DDL_PROJECTS_COMPANY_INDEX)


PARENT_COLUMN = "parent_id"

V72_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    ("companies", PARENT_COLUMN,
     f"ALTER TABLE companies ADD COLUMN {PARENT_COLUMN} INTEGER REFERENCES companies(id) ON DELETE SET NULL"),
)


def apply_v72(conn: sqlite3.Connection) -> None:
    for table, column, statement in V72_COLUMNS:
        present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if present and column not in present:
            conn.execute(statement)
