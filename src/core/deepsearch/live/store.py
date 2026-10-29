
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, fields
from typing import Dict, Iterable, List, Optional, Set

from src.core.deepsearch import constants as K


@dataclass
class LiveFile:

    conversation_id: str
    path: str
    file_kind: str
    family: str
    base_offset: int
    base_line: int
    base_point_id: Optional[str]
    indexed_offset: int
    indexed_lines: int
    last_serial: Optional[str]
    last_serial_offset: Optional[int]
    rows: int
    filter_version: str
    in_scope: int
    scope: Optional[str]
    created_at: str
    indexed_at: str
    id: Optional[int] = None


_COLUMNS = tuple(f.name for f in fields(LiveFile) if f.name != "id")


def get(conn: sqlite3.Connection, path: str) -> Optional[LiveFile]:
    row = conn.execute(f"SELECT {', '.join(_COLUMNS)}, id FROM {K.LIVE_TABLE} WHERE path = ?", (path,)).fetchone()
    return None if row is None else LiveFile(*row)


def of_conversation(conn: sqlite3.Connection, conversation_id: str) -> List[LiveFile]:
    return [LiveFile(*r) for r in conn.execute(
        f"SELECT {', '.join(_COLUMNS)}, id FROM {K.LIVE_TABLE} WHERE conversation_id = ? ORDER BY id",
        (conversation_id,))]


def marked(conn: sqlite3.Connection, mark: str) -> List[LiveFile]:
    return [LiveFile(*r) for r in conn.execute(
        f"SELECT {', '.join(_COLUMNS)}, id FROM {K.LIVE_TABLE} WHERE base_point_id = ? ORDER BY id", (mark,))]


def set_mark(conn: sqlite3.Connection, live_id: int, mark: Optional[str]) -> None:
    conn.execute(f"UPDATE {K.LIVE_TABLE} SET base_point_id = ? WHERE id = ?", (mark, live_id))


def save(conn: sqlite3.Connection, live: LiveFile) -> int:
    values = tuple(getattr(live, c) for c in _COLUMNS)
    if live.id is None:
        cursor = conn.execute(f"INSERT INTO {K.LIVE_TABLE} ({', '.join(_COLUMNS)}) VALUES "
                              f"({', '.join('?' for _ in _COLUMNS)})", values)
        live.id = int(cursor.lastrowid)
    else:
        conn.execute(f"UPDATE {K.LIVE_TABLE} SET {', '.join(c + ' = ?' for c in _COLUMNS)} WHERE id = ?",
                     (*values, live.id))
    return live.id


def delete_file(conn: sqlite3.Connection, live_id: int) -> None:
    conn.execute(f"DELETE FROM {K.FTS_TABLE} WHERE rowid IN (SELECT id FROM {K.ROWS_TABLE} "
                 f"WHERE {K.LIVE_ID_COLUMN} = ?)", (live_id,))
    conn.execute(f"DELETE FROM {K.ROWS_TABLE} WHERE {K.LIVE_ID_COLUMN} = ?", (live_id,))
    conn.execute(f"DELETE FROM {K.FOLDERS_TABLE} WHERE live_id = ?", (live_id,))
    conn.execute(f"DELETE FROM {K.LIVE_TABLE} WHERE id = ?", (live_id,))


def add_folders(conn: sqlite3.Connection, live_id: int, folders: Iterable[str]) -> None:
    conn.executemany(f"INSERT OR IGNORE INTO {K.FOLDERS_TABLE} (live_id, folder) VALUES (?, ?)",
                     [(live_id, folder) for folder in folders])


def folders_of(conn: sqlite3.Connection, live_ids: List[int]) -> Dict[int, Set[str]]:
    out: Dict[int, Set[str]] = {}
    for start in range(0, len(live_ids), 500):
        chunk = live_ids[start:start + 500]
        marks = ", ".join("?" for _ in chunk)
        for live_id, folder in conn.execute(
                f"SELECT live_id, folder FROM {K.FOLDERS_TABLE} WHERE live_id IN ({marks})", chunk):
            out.setdefault(int(live_id), set()).add(folder)
    return out


def delete_main(conn: sqlite3.Connection, conversation_id: str) -> None:
    for (live_id,) in conn.execute(f"SELECT id FROM {K.LIVE_TABLE} WHERE conversation_id = ? AND file_kind = ?",
                                   (conversation_id, K.FILE_CONVERSATION)).fetchall():
        delete_file(conn, int(live_id))
