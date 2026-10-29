
from __future__ import annotations

from typing import Mapping


BASIS_SQL = ("(work_items.state || '|' || work_items.claude_working || '|' || work_items.revision || '|' || COALESCE((SELECT MAX(m.id) FROM work_messages m "
             "WHERE m.item_id = work_items.id AND m.author_key != 'nudge'), 0) || '|' || work_items.claude_read_seq)")
_NOW = f"n.item_id = work_items.id AND n.basis = {BASIS_SQL}"
SELECT_COLS = (f"(SELECT n.count FROM work_item_nudges n WHERE {_NOW}) AS nudge_count, "
               f"(SELECT n.last_at FROM work_item_nudges n WHERE {_NOW}) AS nudge_last_at, "
               f"(SELECT n.stalled_at FROM work_item_nudges n WHERE {_NOW}) AS nudge_stalled_at")
LAST_ACTIVITY_SQL = ("MAX(work_items.updated_at, COALESCE((SELECT MAX(m.created_at) FROM work_messages m "
                     "WHERE m.item_id = work_items.id AND m.author_key != 'nudge'), 0))")

CLAIM_OP_SQL = ("(SELECT w.op FROM work_write_actors w WHERE w.item_id = work_items.id AND w.actor_key = work_items.claude_working_by "
                "ORDER BY w.id DESC LIMIT 1)")


def wire(row: Mapping) -> dict:
    keys = row.keys()
    count = (row["nudge_count"] if "nudge_count" in keys else 0) or 0
    stalled = bool(row["nudge_stalled_at"]) if "nudge_stalled_at" in keys else False
    if not count and not stalled:
        return {}
    return {"nudge": {"count": count, "last_at": row["nudge_last_at"], "stalled": stalled}}
