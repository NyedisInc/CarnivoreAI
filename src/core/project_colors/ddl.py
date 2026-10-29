
from __future__ import annotations

import sqlite3
from typing import Tuple

from src.core.project_colors.legacy_keys import LEGACY_KEY_HEX, LEGACY_KEYS, cycle_key

COLOR_COLUMN = "color"

DDL_PROJECTS_COLOR_COLUMN = f"ALTER TABLE projects ADD COLUMN {COLOR_COLUMN} TEXT"

V61_COLUMNS: Tuple[Tuple[str, str, str], ...] = (("projects", COLOR_COLUMN, DDL_PROJECTS_COLOR_COLUMN),)

_PICK = " ".join(f"WHEN {i} THEN '{key}'" for i, key in enumerate(LEGACY_KEYS))

DDL_COLOR_TRIGGER = (
    "CREATE TRIGGER IF NOT EXISTS trg_projects_color AFTER INSERT ON projects WHEN NEW.color IS NULL BEGIN "
    f"UPDATE projects SET color = CASE abs(random()) % {len(LEGACY_KEYS)} {_PICK} END WHERE id = NEW.id; END"
)


def apply_v61(conn: sqlite3.Connection) -> None:
    present = {row[1] for row in conn.execute("PRAGMA table_info(projects)")}
    if not present:
        return
    if COLOR_COLUMN not in present:
        conn.execute(DDL_PROJECTS_COLOR_COLUMN)
    for position, (project_id,) in enumerate(
        conn.execute(f"SELECT id FROM projects WHERE {COLOR_COLUMN} IS NULL ORDER BY id").fetchall()
    ):
        conn.execute(f"UPDATE projects SET {COLOR_COLUMN} = ? WHERE id = ?", (cycle_key(position), project_id))
    conn.execute(DDL_COLOR_TRIGGER)


def apply_v91(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TRIGGER IF EXISTS trg_projects_color")
    if COLOR_COLUMN not in {row[1] for row in conn.execute("PRAGMA table_info(projects)")}:
        return
    marks = ", ".join("?" for _ in LEGACY_KEYS)
    conn.execute(f"UPDATE projects SET {COLOR_COLUMN} = NULL WHERE {COLOR_COLUMN} IN ({marks})", LEGACY_KEYS)


def apply_v98(conn: sqlite3.Connection) -> None:
    if COLOR_COLUMN not in {row[1] for row in conn.execute("PRAGMA table_info(projects)")}:
        return
    for key, hex_color in LEGACY_KEY_HEX.items():
        conn.execute(f"UPDATE projects SET {COLOR_COLUMN} = ? WHERE {COLOR_COLUMN} = ?", (hex_color, key))
