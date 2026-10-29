
from __future__ import annotations

import sqlite3
from typing import List, Optional, Sequence, Tuple

from src.cplugs.huddle.rules import JOE, REPLY

Reply = Tuple[int, int]
MAX_NAMED = 5


def newest_replies(conn: sqlite3.Connection, list_key: str, since: int, items: Optional[Sequence[int]] = None) -> List[Reply]:
    rows = conn.execute(
        "SELECT m.item_id, MAX(m.id) FROM work_messages m JOIN work_items i ON i.id = m.item_id "
        "WHERE i.list_key = ? AND i.deleted = 0 AND m.author = ? AND m.kind = ? AND m.seq > ? GROUP BY m.item_id ORDER BY m.item_id",
        (list_key, JOE, REPLY, since)).fetchall()
    return [(int(i), int(m)) for i, m in rows if items is None or i in items]


def sentence(replies: Sequence[Reply]) -> str:
    if not replies:
        return ""
    named = "; ".join(f"task {i} (message {m})" for i, m in replies[:MAX_NAMED])
    more = f" and {len(replies) - MAX_NAMED} more" if len(replies) > MAX_NAMED else ""
    return f" the owner replied in the thread of {named}{more}: read a thread with task_manager_tasks_list item=<task id>."
