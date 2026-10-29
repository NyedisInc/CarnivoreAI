
from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any, Mapping, Optional

from src.cplugs.huddle import rules, triggers, waits
from src.cplugs.huddle.rules import CLAUDE, TaskManagerInvalid


def _effective_one_time(conn: sqlite3.Connection, item_id: int, change: Optional[triggers.Plan]) -> Optional[float]:
    if change is not None and change.cancel:
        return None
    row = conn.execute("SELECT fire_at, fired_at, repeat_rule, paused FROM work_item_triggers WHERE item_id = ?", (item_id,)).fetchone()
    stamp = change.fire_at if change is not None and change.fire_at is not None else (row["fire_at"] if row else None)
    rule = (row["repeat_rule"] if row else None) if change is None or change.repeat is triggers.UNSET else change.repeat
    paused = bool(row["paused"]) if row else False
    if change is not None and change.paused is not None:
        paused = bool(change.paused)
    pending = (change is not None and change.fire_at is not None) or (row is not None and row["fired_at"] is None)
    return stamp if pending and rule is None and not paused else None


def check(conn: sqlite3.Connection, row: Mapping[str, Any], new_state: str, actor: str, change: Optional[triggers.Plan],
          parking: Optional[waits.Park]) -> None:
    if actor != CLAUDE or new_state != rules.WAITING:
        return
    fire_at = _effective_one_time(conn, row["id"], change)
    if fire_at is None:
        return
    live = waits.live(conn, row["id"])
    expect = parking.spec.expect_by if parking is not None else (live["expect_by"] if live is not None else None)
    if expect is None or fire_at >= expect:
        return
    when = datetime.fromtimestamp(fire_at).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    raise TaskManagerInvalid(f"this item is scheduled for {when}, before this wait would clear; the fire would be held until the wait ends. "
                        f"Set expect_by before {when}, add a wait_check, or move the schedule (fire_at)")
