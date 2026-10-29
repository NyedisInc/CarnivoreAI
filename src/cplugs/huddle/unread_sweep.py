
from __future__ import annotations

import sqlite3
from typing import Set, Tuple

from src.cplugs.huddle import lane, rules, status_lines

_STALE_WHERE = (
    "deleted = 0 AND attention_seq > seen_seq AND state != ? AND state != ? AND lane != ? "
    "AND NOT EXISTS (SELECT 1 FROM work_messages m WHERE m.item_id = work_items.id AND m.author = 'claude' AND m.seen = 0 "
    "AND COALESCE(m.category, '') != ?) "
    "AND NOT EXISTS (SELECT 1 FROM work_messages q WHERE q.item_id = work_items.id AND q.kind = 'question' AND q.answered = 0)"
)


def sweep_stale_dots(conn: sqlite3.Connection) -> Tuple[list, Set[str]]:
    args = (rules.DONE, rules.REVIEW, lane.SWARM, status_lines.CATEGORY)
    rows = conn.execute(f"SELECT id, list_key FROM work_items WHERE {_STALE_WHERE} ORDER BY id", args).fetchall()
    if not rows:
        return [], set()
    marks = ",".join("?" * len(rows))
    conn.execute(f"UPDATE work_items SET seen_seq = attention_seq WHERE id IN ({marks})", [r[0] for r in rows])
    return [r[0] for r in rows], {r[1] for r in rows}
