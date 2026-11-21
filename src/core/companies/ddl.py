
from __future__ import annotations

import os
import sqlite3
from typing import Iterable, Optional, Tuple

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


FOLDER_COLUMN = "folder"

V105_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    ("companies", FOLDER_COLUMN, f"ALTER TABLE companies ADD COLUMN {FOLDER_COLUMN} TEXT"),
)


def common_project_folder(roots: Iterable[str], home: Optional[str] = None) -> Optional[str]:
    paths = list(roots)
    if not paths or any(not os.path.isabs(p) for p in paths):
        return None
    try:
        common = os.path.commonpath(paths)
    except ValueError:
        return None
    base = os.path.realpath(home or os.path.expanduser("~"))
    resolved = os.path.realpath(common)
    inside_home = resolved != base and resolved.startswith(base + os.sep)
    return common if inside_home and os.path.isdir(common) else None


def apply_v105(conn: sqlite3.Connection) -> None:
    for table, column, statement in V105_COLUMNS:
        present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if present and column not in present:
            conn.execute(statement)
    present = {row[1] for row in conn.execute("PRAGMA table_info(companies)")}
    if FOLDER_COLUMN not in present or COMPANY_COLUMN not in {r[1] for r in conn.execute("PRAGMA table_info(projects)")}:
        return
    for (company_id,) in conn.execute("SELECT id FROM companies WHERE folder IS NULL").fetchall():
        roots = [r[0] for r in conn.execute("SELECT root FROM projects WHERE company_id = ?", (company_id,))]
        folder = common_project_folder(roots)
        if folder is not None:
            conn.execute("UPDATE companies SET folder = ? WHERE id = ?", (folder, company_id))
