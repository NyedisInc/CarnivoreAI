
from __future__ import annotations

import sqlite3
import time
from typing import FrozenSet, Iterable, Optional, Set, Tuple

from src.core.db import transaction

TABLE_REV = "rollup_rev"
TABLE_META = "rollup_meta"
TABLE_RELEASED = "rollup_released"
_REVISION_KEY = "revision"
_ALLOWLIST_KEY = "allowlist"

_DDL = (
    f"CREATE TABLE IF NOT EXISTS {TABLE_META} (key TEXT PRIMARY KEY, value INTEGER NOT NULL) WITHOUT ROWID",
    f"CREATE TABLE IF NOT EXISTS {TABLE_REV} (conversation_id TEXT NOT NULL, hour INTEGER NOT NULL, "
    "rev INTEGER NOT NULL, PRIMARY KEY(conversation_id, hour)) WITHOUT ROWID",
    f"CREATE INDEX IF NOT EXISTS {TABLE_REV}_order ON {TABLE_REV}(rev, hour, conversation_id)",
    "CREATE INDEX IF NOT EXISTS dim_source_conversation ON dim_source(conversation_id)",
)
_BACKFILL = (
    f"INSERT OR IGNORE INTO {TABLE_REV} (conversation_id, hour, rev) "
    "SELECT s.conversation_id, u.t, ? FROM usage_hour u JOIN dim_source s ON s.id = u.src GROUP BY s.conversation_id, u.t "
    "UNION SELECT s.conversation_id, c.t, ? FROM counter_hour c JOIN dim_source s ON s.id = c.src "
    "GROUP BY s.conversation_id, c.t"
)


def exists(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (TABLE_REV,)).fetchone() is not None


def ensure(conn: sqlite3.Connection, now: Optional[float] = None) -> None:
    if exists(conn):
        return
    for statement in _DDL:
        conn.execute(statement)
    seed = int((time.time() if now is None else now) * 1000)
    conn.execute(f"INSERT OR IGNORE INTO {TABLE_META} (key, value) VALUES (?, ?)", (_REVISION_KEY, seed))
    conn.execute(_BACKFILL, (seed, seed))


def current(conn: sqlite3.Connection) -> int:
    if not exists(conn):
        return 0
    row = conn.execute(f"SELECT value FROM {TABLE_META} WHERE key = ?", (_REVISION_KEY,)).fetchone()
    return int(row[0]) if row else 0


def _bump(conn: sqlite3.Connection) -> int:
    conn.execute(f"UPDATE {TABLE_META} SET value = value + 1 WHERE key = ?", (_REVISION_KEY,))
    return int(conn.execute(f"SELECT value FROM {TABLE_META} WHERE key = ?", (_REVISION_KEY,)).fetchone()[0])


def mark(conn: sqlite3.Connection, groups: Iterable[Tuple[str, int]]) -> None:
    pairs: Set[Tuple[str, int]] = set(groups)
    if not pairs:
        return
    ensure(conn)
    rev = _bump(conn)
    conn.executemany(
        f"INSERT INTO {TABLE_REV} (conversation_id, hour, rev) VALUES (?, ?, {rev}) "
        "ON CONFLICT(conversation_id, hour) DO UPDATE SET rev = excluded.rev", sorted(pairs))


def mark_source(conn: sqlite3.Connection, src: int) -> None:
    row = conn.execute("SELECT conversation_id FROM dim_source WHERE id = ?", (src,)).fetchone()
    if row is None:
        return
    hours = [r[0] for r in conn.execute("SELECT t FROM usage_hour WHERE src = ? UNION SELECT t FROM counter_hour WHERE src = ?",
                                        (src, src))]
    mark(conn, ((row[0], hour) for hour in hours))


def _projects_present(conn: sqlite3.Connection) -> Set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM dim_project")}


def _groups_of_projects(conn: sqlite3.Connection, names: Iterable[str]) -> Set[Tuple[str, int]]:
    wanted = sorted(set(names))
    pairs: Set[Tuple[str, int]] = set()
    for start in range(0, len(wanted), 500):
        chunk = wanted[start:start + 500]
        marks = ", ".join("?" for _ in chunk)
        for table, column in (("usage_hour", "u"), ("counter_hour", "c")):
            pairs.update((r[0], int(r[1])) for r in conn.execute(
                f"SELECT s.conversation_id, {column}.t FROM {table} {column} JOIN dim_source s ON s.id = {column}.src "
                f"JOIN dim_project p ON p.id = {column}.project WHERE p.name IN ({marks}) "
                f"GROUP BY s.conversation_id, {column}.t", chunk))
    return pairs


def settle(conn: sqlite3.Connection, allowed: Optional[FrozenSet[str]]) -> FrozenSet[str]:
    if not exists(conn):
        return frozenset()
    conn.execute(f"CREATE TABLE IF NOT EXISTS {TABLE_RELEASED} (name TEXT PRIMARY KEY) WITHOUT ROWID")
    flag = conn.execute(f"SELECT value FROM {TABLE_META} WHERE key = ?", (_ALLOWLIST_KEY,)).fetchone()
    switched_on = bool(flag and flag[0])
    released = {r[0] for r in conn.execute(f"SELECT name FROM {TABLE_RELEASED}")}
    if allowed is None:
        if switched_on or released:
            with transaction(conn):
                conn.execute(f"DELETE FROM {TABLE_RELEASED}")
                conn.execute(f"INSERT OR REPLACE INTO {TABLE_META} (key, value) VALUES (?, 0)", (_ALLOWLIST_KEY,))
        return frozenset()
    exportable = _projects_present(conn) & allowed
    fresh = exportable - released
    if fresh or not switched_on:
        with transaction(conn):
            if not switched_on:
                conn.execute(f"DELETE FROM {TABLE_RELEASED}")
                released = set()
                conn.execute(f"INSERT OR REPLACE INTO {TABLE_META} (key, value) VALUES (?, 1)", (_ALLOWLIST_KEY,))
            else:
                mark(conn, _groups_of_projects(conn, fresh))
            conn.executemany(f"INSERT OR IGNORE INTO {TABLE_RELEASED} (name) VALUES (?)", [(n,) for n in sorted(exportable - released)])
    return frozenset(released - allowed)
