
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.db_reuse.thread_connections import ThreadConnections
from src.core.pipeline import contract as C

_locks: Dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()

_CURSOR_COLUMNS = ("path", "conversation_id", "family", "file_kind", "offset", "lines", "last_serial",
                   "last_serial_offset", "inherit_state", "inherited_start", "inherited_end", "updated_at")


class PluginUnavailable(Exception):
    pass


def db_path(state_dir: Path, plugin: C.Plugin) -> Path:
    folder = Path(state_dir) if plugin.in_state_dir else Path(state_dir) / C.PLUGIN_DIR
    return folder / plugin.db_name


def lock_for(plugin_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(plugin_id, threading.Lock())


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _framework_tables(conn: sqlite3.Connection) -> None:
    conn.execute(f"CREATE TABLE IF NOT EXISTS {C.CURSORS_TABLE} (path TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, "
                 "family TEXT NOT NULL, file_kind TEXT NOT NULL, offset INTEGER NOT NULL, lines INTEGER NOT NULL, "
                 "last_serial TEXT, last_serial_offset INTEGER, inherit_state TEXT NOT NULL, "
                 "inherited_start INTEGER NOT NULL, inherited_end INTEGER NOT NULL, updated_at REAL NOT NULL)")
    conn.execute(f"CREATE TABLE IF NOT EXISTS {C.META_TABLE} (key TEXT PRIMARY KEY, value TEXT)")


def meta(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute(f"SELECT value FROM {C.META_TABLE} WHERE key = ?", (key,)).fetchone()
    return None if row is None else row[0]


def set_meta(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(f"INSERT INTO {C.META_TABLE} (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET "
                 "value = excluded.value", (key, None if value is None else str(value)))


def open_db(state_dir: Path, plugin: C.Plugin, path: Optional[Path] = None) -> sqlite3.Connection:
    from src.core.db import transaction

    target = path or db_path(state_dir, plugin)
    conn: Optional[sqlite3.Connection] = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        conn = _connect(target)
        with transaction(conn):
            _framework_tables(conn)
            current = int(meta(conn, C.META_SCHEMA_VERSION) or 0)
            if current > plugin.schema_version:
                raise PluginUnavailable(f"database schema {current} is newer than the plugin's {plugin.schema_version}")
            if current < plugin.schema_version:
                plugin.migrate(conn, current)
                set_meta(conn, C.META_SCHEMA_VERSION, plugin.schema_version)
                if current == 0:
                    set_meta(conn, C.META_CREATED_AT, time.time())
        return conn
    except PluginUnavailable:
        if conn is not None:
            conn.close()
        raise
    except Exception as exc:  # noqa: BLE001
        if conn is not None:
            conn.close()
        raise PluginUnavailable(f"{type(exc).__name__}: {exc}") from exc


_pooled: Dict[tuple, ThreadConnections] = {}


def pooled_db(state_dir: Path, plugin: C.Plugin) -> sqlite3.Connection:
    path = db_path(state_dir, plugin)
    key = (str(path), plugin.id)
    with _locks_guard:
        pool = _pooled.get(key)
        if pool is None:
            pool = _pooled[key] = ThreadConnections(lambda p: open_db(state_dir, plugin, p))
    try:
        conn = pool.get(path)
    except sqlite3.Error as exc:
        raise PluginUnavailable(f"{type(exc).__name__}: {exc}") from exc
    if conn.in_transaction:
        conn.rollback()
    return conn


def discard_pooled(state_dir: Path, plugin: C.Plugin) -> None:
    path = db_path(state_dir, plugin)
    with _locks_guard:
        pool = _pooled.get((str(path), plugin.id))
    if pool is not None:
        pool.discard(path)


@dataclass
class Cursor:

    path: str
    conversation_id: str
    family: str
    file_kind: str
    offset: int = 0
    lines: int = 0
    last_serial: Optional[str] = None
    last_serial_offset: Optional[int] = None
    inherit_state: str = C.INHERIT_HEAD
    inherited_start: int = 0
    inherited_end: int = 0
    updated_at: float = 0.0

    def position(self) -> tuple:
        return (self.offset, self.lines, self.last_serial, self.last_serial_offset, self.inherit_state,
                self.inherited_start, self.inherited_end)


def get_cursor(conn: sqlite3.Connection, path: str) -> Optional[Cursor]:
    row = conn.execute(f"SELECT {', '.join(_CURSOR_COLUMNS)} FROM {C.CURSORS_TABLE} WHERE path = ?", (path,)).fetchone()
    return None if row is None else Cursor(*row)


def save_cursor(conn: sqlite3.Connection, cursor: Cursor) -> None:
    values = asdict(cursor)
    marks = ", ".join("?" for _ in _CURSOR_COLUMNS)
    updates = ", ".join(f"{c} = excluded.{c}" for c in _CURSOR_COLUMNS[1:])
    conn.execute(f"INSERT INTO {C.CURSORS_TABLE} ({', '.join(_CURSOR_COLUMNS)}) VALUES ({marks}) "
                 f"ON CONFLICT(path) DO UPDATE SET {updates}", [values[c] for c in _CURSOR_COLUMNS])


def delete_cursor(conn: sqlite3.Connection, path: str) -> int:
    return conn.execute(f"DELETE FROM {C.CURSORS_TABLE} WHERE path = ?", (path,)).rowcount


def delete_cursors(conn: sqlite3.Connection, conversation_id: str) -> int:
    return conn.execute(f"DELETE FROM {C.CURSORS_TABLE} WHERE conversation_id = ?", (conversation_id,)).rowcount
