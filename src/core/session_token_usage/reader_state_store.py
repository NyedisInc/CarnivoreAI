
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Collection, Iterator, List, Optional, Sequence, Tuple

import structlog

from src.core.session_token_usage.cache import StatSignature
from src.core.test_write_guard import assert_test_write_allowed

logger = structlog.get_logger()

DB_NAME = "reader_state.db"
FORMAT = "1"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS reader_state (
  reader TEXT NOT NULL, path TEXT NOT NULL, version TEXT NOT NULL,
  size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, off INTEGER NOT NULL,
  head BLOB NOT NULL, tail BLOB NOT NULL, ino INTEGER NOT NULL,
  sig_ino INTEGER, sig_size INTEGER, sig_mtime_ns INTEGER, sig_ctime_ns INTEGER,
  payload TEXT NOT NULL, written_at REAL NOT NULL,
  PRIMARY KEY (reader, path)
) WITHOUT ROWID;
"""

_UPSERT = (
    "INSERT OR REPLACE INTO reader_state (reader, path, version, size, mtime_ns, off, head, "
    "tail, ino, sig_ino, sig_size, sig_mtime_ns, sig_ctime_ns, payload, written_at) "
    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
)


@dataclass(frozen=True)
class StoredRow:

    reader: str
    path: str
    version: str
    size: int
    mtime_ns: int
    offset: int
    head: bytes
    tail: bytes
    ino: int
    sig: Optional[StatSignature]
    payload: str
    written_at: float

    def as_params(self) -> Tuple[object, ...]:
        sig = self.sig if self.sig is not None else (None, None, None, None)
        return (self.reader, self.path, self.version, self.size, self.mtime_ns, self.offset,
                self.head, self.tail, self.ino, *sig, self.payload, self.written_at)


class ReaderStateStore:

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
        self._close_conn()
        assert_test_write_allowed(self._path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._path), timeout=5.0, check_same_thread=False)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=2000")
            conn.executescript(_SCHEMA)
            row = conn.execute("SELECT value FROM meta WHERE key='format'").fetchone()
            if row is None:
                with conn:
                    conn.execute("INSERT INTO meta (key, value) VALUES ('format', ?)", (FORMAT,))
            elif row[0] != FORMAT:
                raise sqlite3.DatabaseError("reader_state format mismatch")
            os.chmod(self._path, 0o600)
        except (sqlite3.Error, OSError):
            conn.close()
            raise
        self._conn = conn
        self._identity = self._file_identity()

    def _close_conn(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def close(self) -> None:
        with self._lock:
            self._close_conn()

    def reset_files(self) -> None:
        with self._lock:
            self._close_conn()
            for suffix in ("", "-wal", "-shm"):
                try:
                    os.unlink(str(self._path) + suffix)
                except FileNotFoundError:
                    continue

    def load(self, reader: str, version: str, limit: int) -> List[StoredRow]:
        with self._session(True) as conn, conn:
            conn.execute(
                "DELETE FROM reader_state WHERE reader = ? AND version != ?", (reader, version)
            )
            rows = conn.execute(
                "SELECT reader, path, version, size, mtime_ns, off, head, tail, ino, sig_ino, "
                "sig_size, sig_mtime_ns, sig_ctime_ns, payload, written_at FROM reader_state "
                "WHERE reader = ? ORDER BY written_at DESC, path", (reader,)
            ).fetchall()
            if len(rows) > limit:
                conn.executemany(
                    "DELETE FROM reader_state WHERE reader = ? AND path = ?",
                    [(reader, r[1]) for r in rows[limit:]],
                )
                rows = rows[:limit]
        out: List[StoredRow] = []
        for r in reversed(rows):
            sig = None if r[9] is None else (r[9], r[10], r[11], r[12])
            out.append(StoredRow(r[0], r[1], r[2], r[3], r[4], r[5], bytes(r[6]), bytes(r[7]),
                                 r[8], sig, r[13], r[14]))
        return out

    def write(
        self, upserts: Sequence[StoredRow], tombstones: Sequence[Tuple[str, str]]
    ) -> None:
        if not upserts and not tombstones:
            return
        with self._session(True) as conn, conn:
            if tombstones:
                conn.executemany(
                    "DELETE FROM reader_state WHERE reader = ? AND path = ?", list(tombstones)
                )
            if upserts:
                conn.executemany(_UPSERT, [row.as_params() for row in upserts])

    def drop_readers_except(self, names: Collection[str]) -> int:
        with self._session(True) as conn, conn:
            marks = ",".join("?" for _ in names) or "''"
            cur = conn.execute(
                f"DELETE FROM reader_state WHERE reader NOT IN ({marks})", tuple(names)
            )
            return cur.rowcount
