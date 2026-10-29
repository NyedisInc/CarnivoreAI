
from __future__ import annotations

HELD_MIGRATION = (
    "CREATE TABLE held_tells ("
    "list_key TEXT PRIMARY KEY, "
    "target TEXT NOT NULL, "
    "label TEXT, "
    "code TEXT, "
    "reason TEXT NOT NULL DEFAULT '', "
    "since REAL NOT NULL, "
    "deadline REAL NOT NULL, "
    "params TEXT NOT NULL DEFAULT '{}') WITHOUT ROWID;"
)
