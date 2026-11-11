
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import structlog

from src.cplugs.sdk.storage import CplugStorage

logger = structlog.get_logger()

MAX_VISITORS_PER_LINK = 20
RETENTION_S = 30 * 86400
PRINT_HEX = 8


class VisitorsFull(Exception):
    pass


@dataclass(frozen=True)
class Visitor:

    id: int
    number: int


@dataclass(frozen=True)
class VisitorRevision:

    number: int
    revision: str
    updated_at: int
    print: str = ""

    def as_wire(self) -> Dict[str, Any]:
        return {"label": f"u{self.number}", "number": self.number, "revision": self.revision, "updated_at": self.updated_at, "print": self.print}


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("ascii", "ignore")).hexdigest()


def find_visitor(storage: CplugStorage, link_id: str, key: str) -> Optional[Visitor]:
    with closing(storage.connect(False)) as conn:
        return find_visitor_in(conn, link_id, key)


def find_visitor_in(conn: sqlite3.Connection, link_id: str, key: str) -> Optional[Visitor]:
    row = conn.execute("SELECT id, number FROM visitors WHERE link_id = ? AND key_hash = ?", (link_id, key_hash(key))).fetchone()
    return None if row is None else Visitor(int(row[0]), int(row[1]))


def visitor_for(storage: CplugStorage, link_id: str, board: str, key: str, now: Optional[float] = None) -> Visitor:
    with closing(storage.connect(True)) as conn:
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")
        try:
            visitor = visitor_in(conn, link_id, board, key, int(time.time() if now is None else now))
            conn.execute("COMMIT")
        except (sqlite3.Error, VisitorsFull):
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    return visitor


def visitor_in(conn: sqlite3.Connection, link_id: str, board: str, key: str, now: int) -> Visitor:
    hashed = key_hash(key)
    row = conn.execute("SELECT id, number FROM visitors WHERE link_id = ? AND key_hash = ?", (link_id, hashed)).fetchone()
    if row is not None:
        return Visitor(int(row[0]), int(row[1]))
    if conn.execute("SELECT COUNT(*) FROM visitors WHERE link_id = ?", (link_id,)).fetchone()[0] >= MAX_VISITORS_PER_LINK:
        logger.warning("publicboard_visitor_cap", link=link_id)
        raise VisitorsFull()
    number = _next_number(conn, board)
    row_id = conn.execute("INSERT INTO visitors (board, link_id, key_hash, number, created_at) VALUES (?, ?, ?, ?, ?)",
                          (board, link_id, hashed, number, now)).lastrowid
    logger.info("publicboard_visitor_new", link=link_id, board=board, number=number)
    return Visitor(int(row_id), number)


def _next_number(conn: sqlite3.Connection, board: str) -> int:
    mark = conn.execute("SELECT last FROM board_numbers WHERE board = ?", (board,)).fetchone()
    top = int(conn.execute("SELECT COALESCE(MAX(number), 0) FROM visitors WHERE board = ?", (board,)).fetchone()[0])
    number = max(int(mark[0]) if mark else 0, top) + 1
    conn.execute("INSERT INTO board_numbers (board, last) VALUES (?, ?) ON CONFLICT (board) DO UPDATE SET last = excluded.last", (board, number))
    return number


def _dumps(body: Mapping[str, Any]) -> str:
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False, sort_keys=True)


def save_draft(storage: CplugStorage, visitor: int, revision: str, body: Mapping[str, Any], now: Optional[float] = None) -> bool:
    text, stamp = _dumps(body), int(time.time() if now is None else now)
    with closing(storage.connect(True)) as conn, conn:
        seen = conn.execute("SELECT body FROM drafts WHERE visitor = ? AND revision = ?", (visitor, revision)).fetchone()
        if seen is not None and seen[0] == text:
            return False
        conn.execute("INSERT INTO drafts (visitor, revision, body, updated_at) VALUES (?, ?, ?, ?) "
                     "ON CONFLICT (visitor, revision) DO UPDATE SET body = excluded.body, updated_at = excluded.updated_at",
                     (visitor, revision, text, stamp))
    return True


def own_draft(storage: CplugStorage, visitor: int, revision: str) -> Optional[Dict[str, Any]]:
    with closing(storage.connect(False)) as conn:
        row = conn.execute("SELECT body FROM drafts WHERE visitor = ? AND revision = ?", (visitor, revision)).fetchone()
    return None if row is None else {"body": json.loads(row[0])}


def answered_revisions(storage: CplugStorage, visitor: int) -> List[str]:
    with closing(storage.connect(False)) as conn:
        rows = conn.execute("SELECT revision, body FROM drafts WHERE visitor = ?", (visitor,)).fetchall()
    return [str(rev) for rev, body in rows if json.loads(body) not in ({"answers": []}, {"payload": {}})]


def body_print(body: Any) -> str:
    raw = body if isinstance(body, bytes) else str(body).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:PRINT_HEX]


def numbers_of(storage: CplugStorage, who: Sequence[Tuple[str, str]]) -> Dict[Tuple[str, str], int]:
    found: Dict[Tuple[str, str], int] = {}
    with closing(storage.connect(False)) as conn:
        for link_id, hashed in who:
            row = conn.execute("SELECT number FROM visitors WHERE link_id = ? AND key_hash = ?", (link_id, hashed)).fetchone()
            if row is not None:
                found[(link_id, hashed)] = int(row[0])
    return found


def list_board(storage: CplugStorage, board: str, now: Optional[float] = None) -> List[VisitorRevision]:
    sql = ("SELECT v.number, d.revision, d.updated_at, d.body FROM drafts d JOIN visitors v ON v.id = d.visitor "
           "WHERE v.board = ? ORDER BY CAST(SUBSTR(d.revision, 2) AS INTEGER), v.number")
    with closing(storage.connect(False)) as conn:
        return [VisitorRevision(int(r[0]), str(r[1]), int(r[2]), body_print(r[3])) for r in conn.execute(sql, (board,))]


def prune(storage: CplugStorage, board: Optional[str] = None, now: Optional[float] = None) -> int:
    cutoff = int(time.time() if now is None else now) - RETENTION_S
    scope, args = ("AND board = ?", (board,)) if board is not None else ("", ())
    with closing(storage.connect(True)) as conn, conn:
        count = conn.execute(f"DELETE FROM drafts WHERE updated_at < ? AND visitor IN (SELECT id FROM visitors WHERE 1 = 1 {scope})",  # noqa: S608
                             (cutoff, *args)).rowcount
        conn.execute(f"DELETE FROM visitors WHERE created_at < ? {scope} AND id NOT IN (SELECT visitor FROM drafts)", (cutoff, *args))  # noqa: S608
    if count:
        logger.info("publicboard_drafts_pruned", board=board, count=count)
    return count


def revision_body(storage: CplugStorage, board: str, number: int, revision: str) -> Optional[Dict[str, Any]]:
    sql = "SELECT d.body FROM drafts d JOIN visitors v ON v.id = d.visitor WHERE v.board = ? AND v.number = ? AND d.revision = ?"
    with closing(storage.connect(False)) as conn:
        row = conn.execute(sql, (board, number, revision)).fetchone()
    return None if row is None else json.loads(row[0])


def delete_revision(storage: CplugStorage, board: str, number: int, revision: Optional[str] = None) -> int:
    with closing(storage.connect(True)) as conn, conn:
        row = conn.execute("SELECT id FROM visitors WHERE board = ? AND number = ?", (board, number)).fetchone()
        if row is None:
            return 0
        if revision is not None:
            count = conn.execute("DELETE FROM drafts WHERE visitor = ? AND revision = ?", (row[0], revision)).rowcount
        else:
            count = conn.execute("DELETE FROM drafts WHERE visitor = ?", (row[0],)).rowcount
            conn.execute("DELETE FROM visitors WHERE id = ?", (row[0],))
    logger.info("publicboard_visitor_removed", board=board, number=number, revision=revision, count=count)
    return count
