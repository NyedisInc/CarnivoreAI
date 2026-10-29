
from __future__ import annotations

import sqlite3
from typing import Any, Mapping, Optional

from src.cplugs.huddle import closures, rules
from src.cplugs.huddle.cards import state_log

RESTORABLE = (rules.OPEN, rules.WAITING, rules.REVIEW)


def is_reopen(actor: str, current: str, approve: Optional[bool]) -> bool:
    return actor == rules.JOE and current in rules.APPROVED_STATES and approve is False


def _owner_put_in_todo(conn: sqlite3.Connection, item_id: int, before_id: Optional[int]) -> bool:
    found = conn.execute("SELECT by FROM work_card_events WHERE item_id = ? AND kind = ? AND to_col = ? AND id < ? ORDER BY id DESC LIMIT 1",
                         (item_id, state_log.KIND, rules.TODO, before_id if before_id is not None else 0)).fetchone()
    return found is not None and found["by"] == "owner"


def state_after_reopen(conn: sqlite3.Connection, row: Mapping[str, Any]) -> str:
    closure = closures.closure_of(conn, row["id"])
    prior = closure["from_state"] if closure is not None and closure["known"] else ""
    if prior in RESTORABLE:
        return prior
    if prior == rules.TODO and _owner_put_in_todo(conn, row["id"], closure["id"]):
        return rules.TODO
    return rules.REVIEW
