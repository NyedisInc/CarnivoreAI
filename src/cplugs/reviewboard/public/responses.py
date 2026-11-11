
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence

import structlog

from src.cplugs.reviewboard.public import drafts
from src.cplugs.sdk.storage import CplugStorage, StorageSpec

logger = structlog.get_logger()

DB_FILE = "responses.db"
MIGRATIONS = (
    """
    CREATE TABLE responses (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        link_id        TEXT NOT NULL,
        board          TEXT NOT NULL,
        revision       TEXT NOT NULL,
        kind           TEXT NOT NULL CHECK (kind IN ('answers', 'comment')),
        name           TEXT,
        body           TEXT NOT NULL,
        client_post_id TEXT NOT NULL,
        created_at     INTEGER NOT NULL,
        forwarded_at   INTEGER,
        UNIQUE (link_id, client_post_id)
    );
    CREATE INDEX responses_board ON responses (board, id);
    CREATE INDEX responses_created ON responses (created_at);
    """,
    """
    CREATE TABLE visitors (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        board      TEXT NOT NULL,
        link_id    TEXT NOT NULL,
        key_hash   TEXT NOT NULL,
        number     INTEGER NOT NULL,
        created_at INTEGER NOT NULL,
        UNIQUE (link_id, key_hash),
        UNIQUE (board, number)
    );
    CREATE TABLE drafts (
        visitor    INTEGER NOT NULL REFERENCES visitors (id) ON DELETE CASCADE,
        revision   TEXT NOT NULL,
        body       TEXT NOT NULL,
        updated_at INTEGER NOT NULL,
        sent_at    INTEGER,
        PRIMARY KEY (visitor, revision)
    );
    ALTER TABLE responses ADD COLUMN visitor INTEGER;
    CREATE TABLE board_numbers (
        board TEXT PRIMARY KEY,
        last  INTEGER NOT NULL
    );
    """,
)
MAX_PER_BOARD = 500
MAX_PER_LINK_PER_DAY = 200
MAX_PER_INSTALL_PER_DAY = 2000
DAY_S = 86400

Kind = Literal["answers", "comment"]


class CapReached(Exception):

    def __init__(self, which: str) -> None:
        super().__init__(which)
        self.which = which


@dataclass(frozen=True)
class Stored:

    id: int
    duplicate: bool
    visitor: Optional[int] = None


@dataclass(frozen=True)
class Response:

    id: int
    link_id: str
    board: str
    revision: str
    kind: str
    name: Optional[str]
    body: Mapping[str, Any]
    created_at: int
    forwarded_at: Optional[int]


def storage_for(folder: Path) -> CplugStorage:
    return CplugStorage(folder, StorageSpec(db=DB_FILE, migrations=MIGRATIONS, private=True))


def _cap_hit(conn: sqlite3.Connection, link_id: str, board: str, now: int) -> Optional[str]:
    since = now - DAY_S
    checks = (("board", "SELECT COUNT(*) FROM responses WHERE board = ? AND forwarded_at IS NULL", (board,), MAX_PER_BOARD),
              ("link", "SELECT COUNT(*) FROM responses WHERE link_id = ? AND created_at > ?", (link_id, since), MAX_PER_LINK_PER_DAY),
              ("install", "SELECT COUNT(*) FROM responses WHERE created_at > ?", (since,), MAX_PER_INSTALL_PER_DAY))
    for which, sql, args, cap in checks:
        if conn.execute(sql, args).fetchone()[0] >= cap:
            return which
    return None


def add(storage: CplugStorage, *, link_id: str, board: str, revision: str, kind: Kind, name: Optional[str], body: Mapping[str, Any],
        client_post_id: str, now: Optional[float] = None, visitor_key: Optional[str] = None, make_visitor: bool = False) -> Stored:
    stamp = int(time.time() if now is None else now)
    with closing(storage.connect(True)) as conn:
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")
        try:
            seen = conn.execute("SELECT id FROM responses WHERE link_id = ? AND client_post_id = ?", (link_id, client_post_id)).fetchone()
            if seen is not None:
                conn.execute("COMMIT")
                return Stored(int(seen[0]), True)
            which = _cap_hit(conn, link_id, board, stamp)
            if which is not None:
                conn.execute("ROLLBACK")
                logger.warning("publicboard_response_cap", link=link_id, cap=which)
                raise CapReached(which)
            visitor = _sender(conn, link_id, board, visitor_key, make_visitor, stamp)
            row_id = conn.execute(
                "INSERT INTO responses (link_id, board, revision, kind, name, body, client_post_id, created_at, visitor) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (link_id, board, revision, kind, name, json.dumps(body, separators=(",", ":"), ensure_ascii=False), client_post_id, stamp,
                 visitor)).lastrowid
            conn.execute("COMMIT")
        except (sqlite3.Error, CapReached):
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    logger.info("publicboard_response_stored", link=link_id, board=board, kind=kind, id=row_id)
    return Stored(int(row_id), False, visitor)


def _sender(conn: sqlite3.Connection, link_id: str, board: str, key: Optional[str], make: bool, now: int) -> Optional[int]:
    if key is None:
        return None
    if not make:
        known = drafts.find_visitor_in(conn, link_id, key)
        return None if known is None else known.id
    try:
        return drafts.visitor_in(conn, link_id, board, key, now).id
    except drafts.VisitorsFull as exc:
        raise CapReached("visitors") from exc


def _response(row: sqlite3.Row) -> Response:
    return Response(row["id"], row["link_id"], row["board"], row["revision"], row["kind"], row["name"], json.loads(row["body"]),
                    row["created_at"], row["forwarded_at"])


def list_board(storage: CplugStorage, board: str) -> List[Response]:
    with closing(storage.connect(False)) as conn:
        return [_response(row) for row in conn.execute("SELECT * FROM responses WHERE board = ? ORDER BY id", (board,))]


def waiting(storage: CplugStorage, board: str) -> int:
    with closing(storage.connect(False)) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM responses WHERE board = ? AND forwarded_at IS NULL", (board,)).fetchone()[0])


def board_of(storage: CplugStorage, response_id: int) -> Optional[str]:
    with closing(storage.connect(False)) as conn:
        row = conn.execute("SELECT board FROM responses WHERE id = ?", (response_id,)).fetchone()
    return None if row is None else str(row[0])


def mark_forwarded(storage: CplugStorage, ids: Sequence[int], now: Optional[float] = None) -> int:
    if not ids:
        return 0
    stamp = int(time.time() if now is None else now)
    marks = ",".join("?" * len(ids))
    with closing(storage.connect(True)) as conn, conn:
        sql = f"UPDATE responses SET forwarded_at = ? WHERE forwarded_at IS NULL AND id IN ({marks})"  # noqa: S608
        return conn.execute(sql, (stamp, *ids)).rowcount


def delete_one(storage: CplugStorage, response_id: int) -> int:
    with closing(storage.connect(True)) as conn, conn:
        count = conn.execute("DELETE FROM responses WHERE id = ?", (response_id,)).rowcount
    logger.info("publicboard_response_deleted", id=response_id, count=count)
    return count


def delete_forwarded(storage: CplugStorage, board: str) -> int:
    with closing(storage.connect(True)) as conn, conn:
        count = conn.execute("DELETE FROM responses WHERE board = ? AND forwarded_at IS NOT NULL", (board,)).rowcount
    logger.info("publicboard_responses_deleted", board=board, count=count)
    return count


def wire(response: Response) -> Dict[str, Any]:
    return {"id": response.id, "revision": response.revision, "kind": response.kind, "name": response.name, "created_at": response.created_at,
            "forwarded_at": response.forwarded_at}
