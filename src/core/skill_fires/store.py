
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

from src.core.skill_fires.parse import Fire
from src.core.test_write_guard import assert_test_write_allowed

DB_NAME = "skill_fires.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS skill_fires (
  path TEXT NOT NULL, off INTEGER NOT NULL, skill TEXT NOT NULL,
  harness TEXT NOT NULL, profile TEXT NOT NULL, session_key TEXT NOT NULL,
  fired_at TEXT, source TEXT NOT NULL,
  PRIMARY KEY (path, off, skill)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS skill_fires_skill ON skill_fires (skill, fired_at);
CREATE TABLE IF NOT EXISTS skill_fire_cursors (
  path TEXT PRIMARY KEY, size INTEGER NOT NULL, head BLOB NOT NULL,
  off INTEGER NOT NULL
) WITHOUT ROWID;
"""


@dataclass(frozen=True)
class Cursor:

    size: int
    head: bytes
    offset: int


@dataclass(frozen=True)
class FireRow:

    skill: str
    fired_at: Optional[str]
    source: str
    harness: str
    profile: str


class SkillFireStore:

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._identity: Optional[Tuple[int, int]] = None

    def _file_identity(self) -> Optional[Tuple[int, int]]:
        try:
            st = os.stat(self._path)
        except FileNotFoundError:
            return None
        return (st.st_dev, st.st_ino)

    @contextmanager
    def _session(self, write: bool) -> Iterator[sqlite3.Connection]:
        if write:
            assert_test_write_allowed(self._path)
        with self._lock:
            if self._conn is None or self._file_identity() != self._identity:
                self._reopen()
            assert self._conn is not None
            yield self._conn

    def _reopen(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._path), timeout=5.0, check_same_thread=False)
        try:
            conn.executescript(_SCHEMA)
        except sqlite3.Error:
            conn.close()
            raise
        self._conn = conn
        self._identity = self._file_identity()

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def cursor_for(self, path: str) -> Optional[Cursor]:
        with self._session(False) as conn:
            row = conn.execute(
                "SELECT size, head, off FROM skill_fire_cursors WHERE path = ?", (path,)
            ).fetchone()
        return Cursor(row[0], bytes(row[1]), row[2]) if row else None

    def apply(self, path: str, *, harness: str, profile: str, session_key: str,
              cursor: Cursor, fires: Sequence[Tuple[int, Fire]], reset: bool) -> None:
        with self._session(True) as conn, conn:
            if reset:
                conn.execute("DELETE FROM skill_fires WHERE path = ?", (path,))
            conn.executemany(
                "INSERT OR IGNORE INTO skill_fires VALUES (?,?,?,?,?,?,?,?)",
                [(path, off, f.skill, harness, profile, session_key, f.fired_at, f.source)
                 for off, f in fires])
            conn.execute(
                "INSERT OR REPLACE INTO skill_fire_cursors VALUES (?,?,?,?)",
                (path, cursor.size, cursor.head, cursor.offset))

    def count(self, path: str) -> int:
        with self._session(False) as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM skill_fires WHERE path = ?", (path,)).fetchone()[0]

    def recent(self, path: str, limit: int = 20) -> List[FireRow]:
        with self._session(False) as conn:
            rows = conn.execute(
                "SELECT skill, fired_at, source, harness, profile FROM skill_fires "
                "WHERE path = ? ORDER BY off DESC, skill LIMIT ?", (path, limit)).fetchall()
        return [FireRow(*r) for r in rows]

    def usage(self, skill: str, cutoffs: Sequence[str]) -> Optional[List[int]]:
        with self._session(False) as conn:
            if conn.execute("SELECT 1 FROM skill_fire_cursors LIMIT 1").fetchone() is None:
                return None
            return [conn.execute(
                "SELECT COUNT(*) FROM skill_fires WHERE skill = ? AND fired_at >= ?",
                (skill, cutoff)).fetchone()[0] for cutoff in cutoffs]

    def usage_by_skill(self, cutoffs: Sequence[str], *, harness: Optional[str] = None,
                       path_marker: Optional[str] = None) -> Optional[Dict[str, List[int]]]:
        where, args = [], []
        if harness is not None:
            where.append("harness = ?")
            args.append(harness)
        if path_marker is not None:
            where.append("instr(path, ?) > 0")
            args.append(path_marker)
        sums = ", ".join("COALESCE(SUM(fired_at >= ?), 0)" for _ in cutoffs)
        sql = f"SELECT skill, {sums} FROM skill_fires" + (f" WHERE {' AND '.join(where)}" if where else "") + " GROUP BY skill"
        with self._session(False) as conn:
            if conn.execute("SELECT 1 FROM skill_fire_cursors LIMIT 1").fetchone() is None:
                return None
            return {row[0]: [int(n) for n in row[1:]] for row in conn.execute(sql, [*cutoffs, *args])}

    def path_scanned(self, marker: str) -> bool:
        with self._session(False) as conn:
            return conn.execute(
                "SELECT 1 FROM skill_fire_cursors WHERE instr(path, ?) > 0 LIMIT 1", (marker,)
            ).fetchone() is not None

    def fires_since(self, skill: str, since: str, limit: int) -> List[Tuple[str, int, str, Optional[str]]]:
        with self._session(False) as conn:
            rows = conn.execute(
                "SELECT path, off, harness, fired_at FROM skill_fires "
                "WHERE skill = ? AND fired_at >= ? ORDER BY fired_at DESC LIMIT ?",
                (skill, since, limit)).fetchall()
        return [(r[0], r[1], r[2], r[3]) for r in rows]

    def offsets_of(self, path: str, after: int) -> List[Tuple[int, str]]:
        with self._session(False) as conn:
            rows = conn.execute(
                "SELECT off, skill FROM skill_fires WHERE path = ? AND off > ? ORDER BY off, skill",
                (path, after)).fetchall()
        return [(r[0], r[1]) for r in rows]

    def max_offset(self, path: str) -> int:
        with self._session(False) as conn:
            row = conn.execute("SELECT MAX(off) FROM skill_fires WHERE path = ?", (path,)).fetchone()
        return -1 if row is None or row[0] is None else int(row[0])

    def max_offset_before(self, path: str, stamp: str) -> int:
        with self._session(False) as conn:
            row = conn.execute(
                "SELECT MAX(off) FROM skill_fires WHERE path = ? "
                "AND (fired_at IS NULL OR substr(fired_at, 1, 19) < ?)", (path, stamp)).fetchone()
        return -1 if row is None or row[0] is None else int(row[0])

    def reset(self) -> None:
        with self._session(True) as conn, conn:
            conn.execute("DELETE FROM skill_fires")
            conn.execute("DELETE FROM skill_fire_cursors")
