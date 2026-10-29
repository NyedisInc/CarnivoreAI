
from __future__ import annotations

import sqlite3

from src.cplugs.huddle import rules
from src.cplugs.sdk import work

CATEGORY = "status"
KEY = "status"
_OWNER, _SYSTEM, _AGENT = "the owner", "carnivore", "an agent"


def who(by: str) -> str:
    if by == "owner":
        return _OWNER
    if by == rules.CARNIVORE_KEY:
        return _SYSTEM
    return _AGENT


def text(by: str, from_state: str, to_state: str, detail: str = "") -> str:
    tail = f" ({detail})" if detail else ""
    return f"status changed from {from_state} to {to_state} by {who(by)}{tail}"


def post(conn: sqlite3.Connection, item_id: int, from_state: str, to_state: str, *, by: str, now: float, detail: str = "") -> None:
    if not from_state or from_state == to_state:
        return
    note(conn, item_id, text(by, from_state, to_state, detail), now)


def note(conn: sqlite3.Connection, item_id: int, words: str, now: float) -> None:
    seq = work.next_seq(conn)
    conn.execute("INSERT INTO work_messages (item_id, author, kind, text, created_at, seq, author_key, parts, category, seen) "
                 "VALUES (?, ?, 'info', ?, ?, ?, ?, '', ?, 1)",
                 (item_id, rules.CLAUDE, words, now, seq, KEY, CATEGORY))
    conn.execute("UPDATE work_items SET seq = ? WHERE id = ? AND seq < ?", (seq, item_id, seq))
