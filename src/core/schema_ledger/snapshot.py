
from __future__ import annotations

import sqlite3


def dump_schema(conn: sqlite3.Connection) -> str:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    rows = conn.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' "
        "ORDER BY type, name").fetchall()
    out = [f"-- user_version {version}"]
    for kind, name, table, sql in rows:
        out.append(f"-- {kind} {name} on {table}")
        out.append((sql or "").rstrip() + ";")
    return "\n".join(out) + "\n"
