
from __future__ import annotations

import sqlite3
from src.core.safe_io.readonly_db import READONLY_TIMEOUT_DEFAULT_S, connect_readonly
import threading
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

DB_NAME = "attention_history.db"
KIND_QUESTION, KIND_NOTICE, KIND_STARTUP, KIND_DONE, KIND_BUSY = "question", "notice", "startup", "done", "busy"
KINDS = frozenset({KIND_QUESTION, KIND_NOTICE, KIND_STARTUP, KIND_DONE, KIND_BUSY})
SPAN_KINDS = frozenset({KIND_QUESTION, KIND_NOTICE, KIND_STARTUP, KIND_DONE})
RETENTION_DAYS = 90
MAX_ROWS_PER_SESSION = 500

_SCHEMA = """
CREATE TABLE IF NOT EXISTS attention_events (
  id INTEGER PRIMARY KEY, session_uuid TEXT NOT NULL, kind TEXT NOT NULL, at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS attention_events_session ON attention_events (session_uuid, at);
"""


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


class AttentionHistoryStore:

    def __init__(self, path: Union[Path, Callable[[], Path]]) -> None:
        self._path_of = path if callable(path) else (lambda: Path(path))
        self._lock = threading.Lock()

    def record(self, session_uuid: str, kind: str, at: datetime) -> bool:
        if kind not in KINDS or not session_uuid:
            return False
        with self._lock, closing(sqlite3.connect(self._path_of(), timeout=10.0)) as conn:
            conn.executescript(_SCHEMA)
            with conn:
                newest = conn.execute("SELECT kind FROM attention_events WHERE session_uuid = ? "
                                      "ORDER BY at DESC, id DESC LIMIT 1", (session_uuid,)).fetchone()
                if newest is not None and newest[0] == kind:
                    return False
                conn.execute("INSERT INTO attention_events (session_uuid, kind, at) VALUES (?,?,?)",
                             (session_uuid, kind, _iso(at)))
                cutoff = _iso(datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS))
                conn.execute("DELETE FROM attention_events WHERE session_uuid = ? AND (at < ? OR id NOT IN "
                             "(SELECT id FROM attention_events WHERE session_uuid = ? ORDER BY at DESC, id DESC LIMIT ?))",
                             (session_uuid, cutoff, session_uuid, MAX_ROWS_PER_SESSION))
        return True


def read_spans(path: Path, session_uuid: str) -> List[Dict[str, Any]]:
    if not Path(path).exists():
        return []
    try:
        with closing(connect_readonly(path, timeout=READONLY_TIMEOUT_DEFAULT_S)) as conn:
            rows = conn.execute("SELECT kind, at FROM attention_events WHERE session_uuid = ? "
                                "ORDER BY at ASC, id ASC", (session_uuid,)).fetchall()
    except sqlite3.Error:
        return []
    spans: List[Dict[str, Any]] = []
    for i, (kind, at) in enumerate(rows):
        if kind not in SPAN_KINDS:
            continue
        end = rows[i + 1][1] if i + 1 < len(rows) else None
        spans.append({"kind": kind, "start": at, "end": end})
    return spans


def has_events(path: Path, session_uuid: str) -> Optional[bool]:
    if not Path(path).exists():
        return False
    try:
        with closing(connect_readonly(path, timeout=READONLY_TIMEOUT_DEFAULT_S)) as conn:
            return conn.execute("SELECT 1 FROM attention_events WHERE session_uuid = ? LIMIT 1",
                                (session_uuid,)).fetchone() is not None
    except sqlite3.Error:
        return None
