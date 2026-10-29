"""The bookmark store: its own small SQLite file, ``bookmarks.db`` in the state directory.

``cloude.db`` takes no schema change for this feature. A bookmark names a point in ONE Claude
conversation (``claude_session_uuid`` plus the record's ``entry_uuid``) and belongs to the session
row it was taken on (``session_uuid``, the durable row id). Because it keeps the conversation it
points into, a bookmark taken before a rewind still works after it: the original transcript is
on disk, so branching from (or rewinding to) a later bookmark is the way back.

Every write names the keyed push topic ``bookmarks:<sessions.id>`` so an open panel re-reads (keyed on
the row id because that is what the live listing hands a browser: ``session_row_id``), and the global key
``bookmarks:*`` (:data:`ALL_KEY`) so the all-sessions list re-reads. Add and delete are the only writes to the
table: a branch or a rewind opens a session and moves a conversation but leaves every bookmark as it was.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

import structlog

from src.core.bookmarks.errors import BookmarkNotFound
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

# state directory
DB_FILENAME = "bookmarks.db"
CREATED_BY = ("owner", "claude")
MAX_LABEL_CHARS = 200
MAX_PER_SESSION = 500
MAX_RECENT = 200

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bookmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_uuid TEXT NOT NULL,
    session_row_id INTEGER,
    claude_session_uuid TEXT NOT NULL,
    entry_uuid TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL CHECK (created_by IN ('owner', 'claude')),
    created_at TEXT NOT NULL,
    snippet TEXT NOT NULL DEFAULT '',
    entry_timestamp TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_bookmarks_session ON bookmarks (session_uuid, id);
"""


@dataclass(frozen=True)
class Bookmark:

    id: int
    session_uuid: str
    session_row_id: Optional[int]
    claude_session_uuid: str
    entry_uuid: str
    label: str
    created_by: str
    created_at: str
    snippet: str
    entry_timestamp: str

    def as_dict(self) -> dict:
        return asdict(self)


class BookmarkStore:

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._ready = False

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        if not self._ready:
            with self._lock:
                conn.executescript(_SCHEMA)
                self._ready = True
        return conn

    def add(self, *, session_uuid: str, session_row_id: Optional[int], claude_session_uuid: str, entry_uuid: str,
            label: str, created_by: str, snippet: str = "", entry_timestamp: str = "") -> Bookmark:
        if created_by not in CREATED_BY:
            raise ValueError(f"created_by must be one of {', '.join(CREATED_BY)}")
        with closing(self._connect()) as conn, conn:
            count = conn.execute("SELECT COUNT(*) FROM bookmarks WHERE session_uuid = ?", (session_uuid,)).fetchone()[0]
            if count >= MAX_PER_SESSION:
                raise ValueError(f"this session already holds {MAX_PER_SESSION} bookmarks; delete some first")
            cur = conn.execute(
                "INSERT INTO bookmarks (session_uuid, session_row_id, claude_session_uuid, entry_uuid, label, "
                "created_by, created_at, snippet, entry_timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session_uuid, session_row_id, claude_session_uuid, entry_uuid, (label or "").strip()[:MAX_LABEL_CHARS],
                 created_by, utc_now(), snippet or "", entry_timestamp or ""))
            row = conn.execute("SELECT * FROM bookmarks WHERE id = ?", (cur.lastrowid,)).fetchone()
        bookmark = Bookmark(**dict(row))
        logger.info("bookmark_added", id=bookmark.id, session_uuid=session_uuid, created_by=created_by)
        _notify(bookmark)
        return bookmark

    def list_for_session(self, session_uuid: str) -> List[Bookmark]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM bookmarks WHERE session_uuid = ? ORDER BY id DESC", (session_uuid,)).fetchall()
        return [Bookmark(**dict(r)) for r in rows]

    def list_recent(self, limit: int = MAX_RECENT) -> List[Bookmark]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM bookmarks ORDER BY id DESC LIMIT ?",
                                (max(1, min(int(limit), MAX_RECENT)),)).fetchall()
        return [Bookmark(**dict(r)) for r in rows]

    def list_for_conversations(self, conversation_ids: List[str]) -> List[Bookmark]:
        if not conversation_ids:
            return []
        marks = ", ".join("?" for _ in conversation_ids)
        with closing(self._connect()) as conn:
            rows = conn.execute(f"SELECT * FROM bookmarks WHERE claude_session_uuid IN ({marks}) AND entry_timestamp != '' "
                                "ORDER BY entry_timestamp, id", list(conversation_ids)).fetchall()
        return [Bookmark(**dict(r)) for r in rows]

    def get(self, bookmark_id: int) -> Bookmark:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM bookmarks WHERE id = ?", (int(bookmark_id),)).fetchone()
        if row is None:
            raise BookmarkNotFound(f"no bookmark {bookmark_id}")
        return Bookmark(**dict(row))

    def delete(self, bookmark_id: int) -> Bookmark:
        bookmark = self.get(bookmark_id)
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark.id,))
        logger.info("bookmark_deleted", id=bookmark.id, session_uuid=bookmark.session_uuid)
        _notify(bookmark)
        return bookmark


def _notify(bookmark: Bookmark) -> None:
    from src.core import resource_push
    from src.core.resource_push import topics

    key = str(bookmark.session_row_id) if bookmark.session_row_id is not None else bookmark.session_uuid
    resource_push.notify(topics.keyed(topics.BOOKMARKS, key))
    resource_push.notify(topics.keyed(topics.BOOKMARKS, topics.ALL_KEY))


_default: Optional[BookmarkStore] = None
_default_lock = threading.Lock()


def get_store() -> BookmarkStore:
    global _default
    with _default_lock:
        if _default is None:
            from src.config import settings

            _default = BookmarkStore(Path(settings.get_state_dir()) / DB_FILENAME)
        return _default


def set_store(store: Optional[BookmarkStore]) -> None:
    global _default
    with _default_lock:
        _default = store
