
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Iterator, List, Optional, Set, Tuple

import structlog

from src.core.safe_io.readonly_db import READONLY_TIMEOUT_QUICK_S, connect_readonly

logger = structlog.get_logger()

PROJECTS_TABLE = "projects"

_PLAIN_ID = re.compile(r"(\(\s*id\s+INTEGER\s+PRIMARY\s+KEY)(\s*,)", re.IGNORECASE)
_AUTOINCREMENT_ID = re.compile(r"\(\s*id\s+INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\s*,", re.IGNORECASE)

ID_COLUMN = "project_id"
ID_COLUMN_SUFFIX = "_project_id"
KEY_COLUMNS = frozenset({"list_key", "project_key", "scope", "thread_key"})
SCOPE_PREFIX = "project:"
_MAX_DIGITS = 18
MAX_SAFE_ID = 9007199254740991

AUTOMATIONS_FOLDER = "automations"
AUTOMATIONS_DB = "automations.db"
AUTOMATIONS_TABLE = "automations"

_SEQUENCE_PROBE = "_v110_sequence_probe"


class ProjectIdsMigrationError(sqlite3.DatabaseError):
    pass


def apply_v110(conn: sqlite3.Connection) -> None:
    sql = _stored_sql(conn)
    if sql is None:
        return
    if not _AUTOINCREMENT_ID.search(sql):
        _add_autoincrement(conn, sql)
    seed_sequence(conn, highest_project_id(conn))


def _stored_sql(conn: sqlite3.Connection) -> Optional[str]:
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (PROJECTS_TABLE,)).fetchone()
    return row[0] if row and row[0] else None


def _add_autoincrement(conn: sqlite3.Connection, sql: str) -> None:
    new_sql, count = _PLAIN_ID.subn(r"\1 AUTOINCREMENT\2", sql)
    if count != 1:
        raise ProjectIdsMigrationError(f"{PROJECTS_TABLE} does not carry one plain id INTEGER PRIMARY KEY column: {sql!r}")
    before = _fk_report(conn)
    _ensure_sequence_table(conn)
    conn.execute("PRAGMA writable_schema=ON")
    try:
        conn.execute("UPDATE sqlite_master SET sql = ? WHERE type = 'table' AND name = ?", (new_sql, PROJECTS_TABLE))
    finally:
        conn.execute("PRAGMA writable_schema=RESET")
    _bump_schema_cookie(conn)
    stored = _stored_sql(conn) or ""
    if stored != new_sql or not _AUTOINCREMENT_ID.search(stored):
        raise ProjectIdsMigrationError(f"{PROJECTS_TABLE} did not reparse with AUTOINCREMENT: {stored!r}")
    after = _fk_report(conn)
    if after != before:
        raise ProjectIdsMigrationError(f"foreign key check changed across the edit: {len(before)} -> {len(after)} rows")


def _bump_schema_cookie(conn: sqlite3.Connection) -> None:
    cookie = int(conn.execute("PRAGMA schema_version").fetchone()[0])
    conn.execute(f"PRAGMA schema_version = {cookie + 1}")


def _ensure_sequence_table(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sqlite_sequence'").fetchone():
        return
    conn.execute(f"CREATE TABLE {_SEQUENCE_PROBE} (id INTEGER PRIMARY KEY AUTOINCREMENT)")
    conn.execute(f"DROP TABLE {_SEQUENCE_PROBE}")


def _fk_report(conn: sqlite3.Connection) -> List[Tuple[object, ...]]:
    rows: List[Tuple[object, ...]] = []
    for table in sorted({PROJECTS_TABLE} | {t for t, _ in _project_fk_columns(conn)}):
        rows.extend(tuple(r) for r in conn.execute(f'PRAGMA foreign_key_check("{table}")'))
    return sorted(rows, key=repr)


def _tables(conn: sqlite3.Connection) -> List[str]:
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\' "
        "AND upper(sql) NOT LIKE 'CREATE VIRTUAL TABLE%' ORDER BY name")]


def _project_fk_columns(conn: sqlite3.Connection) -> Set[Tuple[str, str]]:
    found: Set[Tuple[str, str]] = set()
    for table in _tables(conn):
        for fk in conn.execute(f'PRAGMA foreign_key_list("{table}")'):
            if str(fk[2]).lower() == PROJECTS_TABLE:
                found.add((table, fk[3]))
    return found


def _reference_columns(conn: sqlite3.Connection) -> Iterator[Tuple[str, str, bool]]:
    fk = _project_fk_columns(conn)
    for table in _tables(conn):
        for col in conn.execute(f'PRAGMA table_info("{table}")'):
            name = col[1]
            lowered = name.lower()
            if (table, name) in fk or lowered == ID_COLUMN or lowered.endswith(ID_COLUMN_SUFFIX):
                yield table, name, False
            elif lowered in KEY_COLUMNS:
                yield table, name, True


def _max_in(conn: sqlite3.Connection, table: str, column: str, is_key: bool) -> int:
    c = f'"{column}"'
    digits = f"({{v}} <> '' AND {{v}} NOT GLOB '*[^0-9]*' AND length({{v}}) <= {_MAX_DIGITS})"
    plain = digits.format(v=c)
    if is_key:
        tail = f"substr({c}, {len(SCOPE_PREFIX) + 1})"
        scoped = f"({c} GLOB '{SCOPE_PREFIX}[0-9]*' AND {digits.format(v=tail)})"
        value = f"CAST(CASE WHEN {scoped} THEN {tail} ELSE {c} END AS INTEGER)"
        where = f"typeof({c}) = 'text' AND ({plain} OR {scoped})"
    else:
        value = f"CAST({c} AS INTEGER)"
        where = f"typeof({c}) = 'integer' OR (typeof({c}) = 'text' AND {plain})"
    sql = f'SELECT MAX({value}) FROM "{table}" WHERE ({where}) AND {value} <= {MAX_SAFE_ID}'
    row = conn.execute(sql).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def highest_project_id(conn: sqlite3.Connection) -> int:
    best = max(_sequence_value(conn), _automations_max(conn), _own_max(conn))
    for table, column, is_key in _reference_columns(conn):
        best = max(best, _max_in(conn, table, column, is_key))
    return best


def _own_max(conn: sqlite3.Connection) -> int:
    if _stored_sql(conn) is None:
        return 0
    row = conn.execute(f'SELECT MAX(id) FROM "{PROJECTS_TABLE}"').fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _automations_path(conn: sqlite3.Connection) -> Optional[Path]:
    main = next((r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"), "")
    return Path(main).parent / AUTOMATIONS_FOLDER / AUTOMATIONS_DB if main else None


def _automations_max(conn: sqlite3.Connection) -> int:
    path = _automations_path(conn)
    if path is None or not path.is_file():
        return 0
    try:
        ro = connect_readonly(path, timeout=READONLY_TIMEOUT_QUICK_S)
        try:
            return _max_in(ro, AUTOMATIONS_TABLE, "project_id", False)
        finally:
            ro.close()
    except sqlite3.Error as exc:
        logger.warning("project_ids_automations_unreadable", path=str(path), error=str(exc),
                       error_type=type(exc).__name__)
        return 0


def _sequence_value(conn: sqlite3.Connection) -> int:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sqlite_sequence'").fetchone():
        return 0
    row = conn.execute("SELECT seq FROM sqlite_sequence WHERE name = ?", (PROJECTS_TABLE,)).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def seed_sequence(conn: sqlite3.Connection, floor: int) -> None:
    if floor <= 0:
        return
    if conn.execute("SELECT 1 FROM sqlite_sequence WHERE name = ?", (PROJECTS_TABLE,)).fetchone():
        conn.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = ? AND seq < ?", (floor, PROJECTS_TABLE, floor))
    else:
        conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)", (PROJECTS_TABLE, floor))
