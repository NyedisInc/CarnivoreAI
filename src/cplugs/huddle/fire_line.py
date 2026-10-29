
from __future__ import annotations

import sqlite3

from src.cplugs.huddle import status_lines

PREFIX = "scheduled wake-up sent to "
LEAD_SUFFIX = "the list's lead"
GONE_SUFFIX = "the task's own session is gone"


def line(label: str, is_lead: bool, fell_back: bool = False) -> str:
    notes = [LEAD_SUFFIX] * is_lead + [GONE_SUFFIX] * fell_back
    return f"{PREFIX}{label}" + (f" ({'; '.join(notes)})" if notes else "")


def record(conn: sqlite3.Connection, item_id: int, label: str, is_lead: bool, now: float, fell_back: bool = False) -> bool:
    words = line(label, is_lead, fell_back)
    repeating = conn.execute("SELECT repeat_rule FROM work_item_triggers WHERE item_id = ?", (item_id,)).fetchone()
    if repeating is not None and repeating[0]:
        last = conn.execute("SELECT text FROM work_messages WHERE item_id = ? AND author_key = ? AND text LIKE ? ORDER BY seq DESC LIMIT 1",
                            (item_id, status_lines.KEY, PREFIX + "%")).fetchone()
        if last is not None and last[0] == words:
            return False
    status_lines.note(conn, item_id, words, now)
    return True
