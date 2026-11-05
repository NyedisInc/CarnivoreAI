
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

KIND_TURN = "turn"
KIND_SAFETY = "safety"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS turn_checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_uuid TEXT NOT NULL,
    conversation TEXT NOT NULL DEFAULT '',
    prompt_uuid TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('turn', 'safety')),
    work_tree TEXT NOT NULL,
    shadow TEXT NOT NULL,
    ref TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    tree_sha TEXT NOT NULL,
    head_sha TEXT,
    left_out TEXT NOT NULL DEFAULT '[]',
    capture_ms INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    UNIQUE (session_uuid, prompt_uuid, kind)
);
CREATE INDEX IF NOT EXISTS ix_turn_checkpoints_session ON turn_checkpoints (session_uuid, created_at);
CREATE TABLE IF NOT EXISTS checkpoint_repos (
    shadow TEXT PRIMARY KEY,
    work_tree TEXT NOT NULL,
    disabled_reason TEXT,
    last_ms INTEGER,
    updated_at REAL NOT NULL
);
"""


@dataclass(frozen=True)
class Checkpoint:

    id: int
    session_uuid: str
    conversation: str
    prompt_uuid: str
    kind: str
    work_tree: str
    shadow: str
    ref: str
    commit_sha: str
    tree_sha: str
    head_sha: Optional[str]
    left_out: List[str]
    capture_ms: int
    created_at: float

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def _row(r: sqlite3.Row) -> Checkpoint:
    d = dict(r)
    d["left_out"] = json.loads(d.get("left_out") or "[]")
    return Checkpoint(**d)


class CheckpointStore:

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def put(self, *, session_uuid: str, conversation: str, prompt_uuid: str, kind: str, work_tree: str, shadow: str,
            ref: str, commit_sha: str, tree_sha: str, head_sha: Optional[str], left_out: Sequence[str],
            capture_ms: int, now: Optional[float] = None) -> Checkpoint:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO turn_checkpoints (session_uuid, conversation, prompt_uuid, kind, work_tree, shadow, ref,"
                " commit_sha, tree_sha, head_sha, left_out, capture_ms, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT (session_uuid, prompt_uuid, kind) DO UPDATE SET conversation=excluded.conversation,"
                " work_tree=excluded.work_tree, shadow=excluded.shadow, ref=excluded.ref,"
                " commit_sha=excluded.commit_sha, tree_sha=excluded.tree_sha, head_sha=excluded.head_sha,"
                " left_out=excluded.left_out, capture_ms=excluded.capture_ms, created_at=excluded.created_at",
                (session_uuid, conversation, prompt_uuid, kind, work_tree, shadow, ref, commit_sha, tree_sha, head_sha,
                 json.dumps(list(left_out)), int(capture_ms), time.time() if now is None else now))
            row = conn.execute("SELECT * FROM turn_checkpoints WHERE session_uuid=? AND prompt_uuid=? AND kind=?",
                               (session_uuid, prompt_uuid, kind)).fetchone()
        _notify([session_uuid])
        return _row(row)

    def for_session(self, session_uuid: str) -> List[Checkpoint]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM turn_checkpoints WHERE session_uuid=? ORDER BY created_at DESC, id DESC",
                                (session_uuid,)).fetchall()
        return [_row(r) for r in rows]

    def sessions(self) -> List[str]:
        with closing(self._connect()) as conn:
            return [r[0] for r in conn.execute("SELECT DISTINCT session_uuid FROM turn_checkpoints").fetchall()]

    def pinned_prompts(self, session_uuid: str) -> set:
        with closing(self._connect()) as conn:
            try:
                rows = conn.execute("SELECT entry_uuid FROM bookmarks WHERE session_uuid=?", (session_uuid,)).fetchall()
            except sqlite3.OperationalError:
                return set()
        return {r[0] for r in rows}

    def delete(self, ids: Sequence[int]) -> None:
        if not ids:
            return
        with closing(self._connect()) as conn, conn:
            marks = ",".join("?" * len(ids))
            owners = [r[0] for r in conn.execute(
                f"SELECT DISTINCT session_uuid FROM turn_checkpoints WHERE id IN ({marks})", list(ids)).fetchall()]
            conn.executemany("DELETE FROM turn_checkpoints WHERE id=?", [(i,) for i in ids])
        _notify(owners)

    def repo_state(self, shadow: str) -> Optional[sqlite3.Row]:
        with closing(self._connect()) as conn:
            return conn.execute("SELECT * FROM checkpoint_repos WHERE shadow=?", (shadow,)).fetchone()

    def disabled_repos(self) -> List[sqlite3.Row]:
        with closing(self._connect()) as conn:
            return conn.execute("SELECT * FROM checkpoint_repos WHERE disabled_reason IS NOT NULL").fetchall()

    def set_repo_state(self, shadow: str, work_tree: str, *, last_ms: Optional[int],
                       disabled_reason: Optional[str]) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO checkpoint_repos (shadow, work_tree, disabled_reason, last_ms, updated_at) VALUES (?,?,?,?,?)"
                " ON CONFLICT (shadow) DO UPDATE SET work_tree=excluded.work_tree,"
                " disabled_reason=excluded.disabled_reason, last_ms=excluded.last_ms, updated_at=excluded.updated_at",
                (shadow, work_tree, disabled_reason, last_ms, time.time()))


_default: Optional[CheckpointStore] = None


def state_root() -> Path:
    from src.config import settings

    return Path(settings.get_state_dir())


def _notify(session_uuids: Sequence[str]) -> None:
    from src.core import resource_push
    from src.core.bookmarks import rows
    from src.core.bookmarks.errors import BookmarkError
    from src.core.resource_push import topics

    for uuid in dict.fromkeys(session_uuids):
        try:
            key = str(rows.read_row(uuid).id)
        except BookmarkError:
            key = uuid
        resource_push.notify(topics.keyed(topics.CHECKPOINTS, key))
    if session_uuids:
        resource_push.notify(topics.keyed(topics.CHECKPOINTS, topics.ALL_KEY))


def get_store() -> CheckpointStore:
    global _default
    if _default is None:
        _default = CheckpointStore(state_root() / "bookmarks.db")
    return _default


def set_store(store: Optional[CheckpointStore]) -> None:
    global _default
    _default = store
