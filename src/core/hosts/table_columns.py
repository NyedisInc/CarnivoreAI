
from __future__ import annotations

import os
import sqlite3
import threading
from typing import Dict, FrozenSet, List, Tuple

_MAX_ENTRIES = 1024

_LOCK = threading.Lock()
_CACHE: Dict[Tuple[str, Tuple[int, int], str, str], Tuple[int, FrozenSet[str]]] = {}


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _direct(conn: sqlite3.Connection, schema: str, table: str) -> FrozenSet[str]:
    rows = conn.execute(f"PRAGMA {_quote(schema)}.table_info({_quote(table)})")
    return frozenset(str(row[1]) for row in rows)


def _schema_columns(
    conn: sqlite3.Connection, schema: str, file: str, table: str
) -> FrozenSet[str]:
    if not file or conn.in_transaction:
        return _direct(conn, schema, table)
    try:
        st = os.stat(file)
    except OSError:
        return _direct(conn, schema, table)
    version = int(conn.execute(f"PRAGMA {_quote(schema)}.schema_version").fetchone()[0])
    key = (file, (st.st_dev, st.st_ino), schema, table)
    with _LOCK:
        hit = _CACHE.get(key)
    if hit is not None and hit[0] == version:
        return hit[1]
    cols = _direct(conn, schema, table)
    with _LOCK:
        if len(_CACHE) >= _MAX_ENTRIES:
            _CACHE.clear()
        _CACHE[key] = (version, cols)
    return cols


def table_columns(conn: sqlite3.Connection, table: str) -> FrozenSet[str]:
    schemas: List[Tuple[int, str, str]] = []
    for row in conn.execute("PRAGMA database_list"):
        rank = 0 if row[1] == "temp" else 1 if row[1] == "main" else 2
        schemas.append((rank, str(row[1]), str(row[2] or "")))
    for _rank, name, file in sorted(schemas, key=lambda s: s[0]):
        cols = _schema_columns(conn, name, file, table)
        if cols:
            return cols
    return frozenset()
