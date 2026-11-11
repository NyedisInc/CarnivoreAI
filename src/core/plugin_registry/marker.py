
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional, Tuple

TABLE = "plugin_registry_marker"

DDL_V104: Tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS {TABLE} (
        id                INTEGER PRIMARY KEY CHECK (id = 1),
        generation        INTEGER NOT NULL,
        schema            INTEGER NOT NULL,
        migrated_at       TEXT,
        migration_version INTEGER NOT NULL DEFAULT 0
    )""",
)


@dataclass(frozen=True)
class Marker:

    generation: int
    schema: int
    migrated_at: Optional[str]
    migration_version: int


def apply_v104(conn: sqlite3.Connection) -> None:
    for statement in DDL_V104:
        conn.execute(statement)


def read_marker(conn: sqlite3.Connection) -> Optional[Marker]:
    try:
        row = conn.execute(f"SELECT generation, schema, migrated_at, migration_version FROM {TABLE} WHERE id = 1").fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return None
        raise
    return Marker(int(row[0]), int(row[1]), row[2], int(row[3])) if row else None


def write_marker(conn: sqlite3.Connection, generation: int, schema: int, migration_version: Optional[int] = None,
                 migrated_at: Optional[str] = None) -> None:
    held = read_marker(conn)
    version = migration_version if migration_version is not None else (held.migration_version if held else 0)
    stamp = migrated_at if migrated_at is not None else (held.migrated_at if held else None)
    conn.execute(
        f"INSERT INTO {TABLE} (id, generation, schema, migrated_at, migration_version) VALUES (1, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET generation = excluded.generation, schema = excluded.schema, "
        "migrated_at = excluded.migrated_at, migration_version = excluded.migration_version",
        (generation, schema, stamp, version),
    )
    conn.commit()
