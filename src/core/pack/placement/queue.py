
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, List, Optional

from src.core.mcp import family_signals

QUEUED, PLACED, CANCELLED, EXPIRED = "queued", "placed", "cancelled", "expired"
EXPIRE_AFTER_SECONDS = 3600.0
MAX_REQUEST_BYTES = 16 * 1024


def _row(row: sqlite3.Row) -> Dict[str, Any]:
    return {"id": row[0], "request": json.loads(row[1]), "queued_at": row[2], "attempts": row[3], "state": row[4],
            "last_reason": row[5]}


def enqueue(conn: sqlite3.Connection, request: Dict[str, Any], reason: str, *, now: Optional[float] = None) -> int:
    body = json.dumps(request, separators=(",", ":"))
    if len(body) > MAX_REQUEST_BYTES:
        raise ValueError("a queued request is at most 16 KiB")
    with conn:
        cur = conn.execute("INSERT INTO pack_spawn_queue (request_json, queued_at, state, last_reason) VALUES (?, ?, ?, ?)",
                           (body, time.time() if now is None else now, QUEUED, reason[:500]))
    family_signals.invalidate("pack")
    return int(cur.lastrowid)


def list_queue(conn: sqlite3.Connection, states: tuple = (QUEUED,)) -> List[Dict[str, Any]]:
    marks = ",".join("?" for _ in states)
    return [_row(r) for r in conn.execute("SELECT id, request_json, queued_at, attempts, state, last_reason "
                                          f"FROM pack_spawn_queue WHERE state IN ({marks}) ORDER BY id", states)]


def count_queued(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM pack_spawn_queue WHERE state = ?", (QUEUED,)).fetchone()[0])


def _set(conn: sqlite3.Connection, queue_id: int, state: str, reason: Optional[str], *, expected: str = QUEUED) -> bool:
    with conn:
        cur = conn.execute("UPDATE pack_spawn_queue SET state = ?, attempts = attempts + 1, last_reason = COALESCE(?, last_reason) "
                           "WHERE id = ? AND state = ?", (state, reason[:500] if reason else None, queue_id, expected))
    family_signals.invalidate("pack")
    return cur.rowcount == 1


def cancel(conn: sqlite3.Connection, queue_id: int) -> bool:
    return _set(conn, queue_id, CANCELLED, "cancelled by the owner")


def mark_placed(conn: sqlite3.Connection, queue_id: int, reason: str) -> bool:
    return _set(conn, queue_id, PLACED, reason)


def note_attempt(conn: sqlite3.Connection, queue_id: int, reason: str) -> None:
    with conn:
        conn.execute("UPDATE pack_spawn_queue SET attempts = attempts + 1, last_reason = ? WHERE id = ? AND state = ?",
                     (reason[:500], queue_id, QUEUED))


def expire_old(conn: sqlite3.Connection, *, now: Optional[float] = None) -> List[Dict[str, Any]]:
    cutoff = (time.time() if now is None else now) - EXPIRE_AFTER_SECONDS
    old = [r for r in list_queue(conn) if r["queued_at"] <= cutoff]
    for row in old:
        _set(conn, row["id"], EXPIRED, "unplaced for an hour, dropped")
    return old
