
from __future__ import annotations

import json
import sqlite3
import threading
from collections import OrderedDict
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from src.core.test_write_guard import assert_test_write_allowed

DB_NAME = "skill_watch.db"

MAX_CACHED_CURSORS = 1024

_SCHEMA = """
CREATE TABLE IF NOT EXISTS drift_baseline (
  install_id TEXT NOT NULL, digest TEXT NOT NULL, relpath TEXT NOT NULL,
  mode TEXT NOT NULL, sha256 TEXT NOT NULL,
  PRIMARY KEY (install_id, relpath)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS drift_state (
  install_id TEXT PRIMARY KEY, checked_at REAL NOT NULL, row_digest TEXT NOT NULL,
  state TEXT NOT NULL, changed_files TEXT
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS tripwire_raised (
  session_key TEXT NOT NULL, skill TEXT NOT NULL, category TEXT NOT NULL,
  PRIMARY KEY (session_key, skill, category)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS tripwire_cursor (
  path TEXT PRIMARY KEY, off INTEGER NOT NULL
) WITHOUT ROWID;
"""


@dataclass(frozen=True)
class DriftRecord:

    install_id: str
    checked_at: float
    row_digest: str
    state: str
    changed_files: Optional[List[str]]


class SkillWatchStore:

    def __init__(self, path: Path) -> None:
        self._path = path
        self._ready = False
        self._cursors: "OrderedDict[str, int]" = OrderedDict()
        self._cursor_lock = threading.Lock()

    def _connect(self, write: bool) -> sqlite3.Connection:
        if not write and not self._path.exists():
            memory = sqlite3.connect(":memory:")
            memory.executescript(_SCHEMA)
            return memory
        assert_test_write_allowed(self._path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._path), timeout=5.0)
        if write or not self._ready:
            conn.executescript(_SCHEMA)
            self._ready = True
        return conn

    def baseline(self, install_id: str, digest: str) -> Optional[Dict[str, Tuple[str, str]]]:
        with closing(self._connect(False)) as conn:
            rows = conn.execute(
                "SELECT relpath, mode, sha256 FROM drift_baseline WHERE install_id = ? AND digest = ?",
                (install_id, digest)).fetchall()
        return {r[0]: (r[1], r[2]) for r in rows} or None

    def save_baseline(self, install_id: str, digest: str,
                      entries: Sequence[Tuple[str, str, str]]) -> None:
        with closing(self._connect(True)) as conn, conn:
            conn.execute("DELETE FROM drift_baseline WHERE install_id = ?", (install_id,))
            conn.executemany(
                "INSERT INTO drift_baseline VALUES (?,?,?,?,?)",
                [(install_id, digest, rel, mode, sha) for rel, mode, sha in entries])

    def save_drift(self, record: DriftRecord) -> None:
        changed = None if record.changed_files is None else json.dumps(record.changed_files)
        with closing(self._connect(True)) as conn, conn:
            conn.execute("INSERT OR REPLACE INTO drift_state VALUES (?,?,?,?,?)",
                         (record.install_id, record.checked_at, record.row_digest, record.state, changed))

    def drift(self, install_id: str) -> Optional[DriftRecord]:
        with closing(self._connect(False)) as conn:
            row = conn.execute(
                "SELECT install_id, checked_at, row_digest, state, changed_files "
                "FROM drift_state WHERE install_id = ?", (install_id,)).fetchone()
        if row is None:
            return None
        return DriftRecord(row[0], row[1], row[2], row[3], None if row[4] is None else json.loads(row[4]))

    def forget(self, install_id: str) -> int:
        if not self._path.exists():
            return 0
        with closing(self._connect(True)) as conn, conn:
            removed = conn.execute("DELETE FROM drift_baseline WHERE install_id = ?", (install_id,)).rowcount
            removed += conn.execute("DELETE FROM drift_state WHERE install_id = ?", (install_id,)).rowcount
        return removed

    def claim_alert(self, session_key: str, skill: str, category: str) -> bool:
        with closing(self._connect(True)) as conn, conn:
            cur = conn.execute("INSERT OR IGNORE INTO tripwire_raised VALUES (?,?,?)",
                               (session_key, skill, category))
            return cur.rowcount == 1

    def tripwire_offset(self, path: str) -> Optional[int]:
        with self._cursor_lock:
            known = self._cursors.get(path)
            if known is not None:
                self._cursors.move_to_end(path)
        if known is not None:
            return known
        with closing(self._connect(False)) as conn:
            row = conn.execute("SELECT off FROM tripwire_cursor WHERE path = ?", (path,)).fetchone()
        if row is None:
            return None
        self._remember_cursor(path, int(row[0]))
        return int(row[0])

    def set_tripwire_offset(self, path: str, offset: int) -> None:
        with closing(self._connect(True)) as conn, conn:
            conn.execute("INSERT OR REPLACE INTO tripwire_cursor VALUES (?,?)", (path, offset))
        self._remember_cursor(path, offset)

    def _remember_cursor(self, path: str, offset: int) -> None:
        with self._cursor_lock:
            self._cursors[path] = offset
            self._cursors.move_to_end(path)
            while len(self._cursors) > MAX_CACHED_CURSORS:
                self._cursors.popitem(last=False)


def default_watch_store() -> SkillWatchStore:
    from src.config import settings  # noqa: PLC0415
    return SkillWatchStore(Path(settings.get_state_dir()) / DB_NAME)
