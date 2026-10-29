
from __future__ import annotations

import sqlite3
from typing import Mapping

from src.cplugs.huddle import closures, rules


def is_cancelled(conn: sqlite3.Connection, row: Mapping) -> bool:
    if row["state"] not in rules.APPROVED_STATES:
        return False
    closure = closures.closure_of(conn, row["id"])
    return closure is not None and closure["outcome"] == closures.CANCELLED


def lands_unread(conn: sqlite3.Connection, row: Mapping, notify: bool) -> bool:
    return notify or is_cancelled(conn, row)
