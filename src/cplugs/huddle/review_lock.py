
from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Any, Dict, List, Mapping, Optional, Sequence

from src.cplugs.huddle import blockers, fork as forks, lane, rules
from src.cplugs.huddle.rules import JOE, TaskManagerLocked

READY_FOR_REVIEW = (rules.REVIEW, *sorted(rules.APPROVED_STATES))
READY_FOR_TICK = tuple(sorted(rules.APPROVED_STATES))
SUBTASKS, BLOCKERS, BOTH = "subtasks", "blockers", "subtasks_and_blockers"
SUBTASKS_KEY, BLOCKERS_KEY = "subtasks", "blockers"


def subtasks_not_in(conn: sqlite3.Connection, item_id: int, ready: Sequence[str], *, before_id: Optional[int] = None) -> List[Dict[str, Any]]:
    marks = ", ".join("?" for _ in ready)
    sql = f"SELECT id, title, text, state FROM work_items WHERE forked_from = ? AND deleted = 0 AND state NOT IN ({marks})"
    args: List[Any] = [item_id, *ready]
    if before_id is not None:
        sql += " AND id < ?"
        args.append(before_id)
    return [{"id": r["id"], "title": forks.name_of(r), "state": r["state"]} for r in conn.execute(sql + " ORDER BY id", args)]


def review_subtasks(conn: sqlite3.Connection, item_id: int) -> List[Dict[str, Any]]:
    return subtasks_not_in(conn, item_id, READY_FOR_REVIEW)


def live_blockers(conn: sqlite3.Connection, item_id: int, now: float) -> List[Dict[str, Any]]:
    if not blockers.is_held(conn, item_id, now):
        return []
    rows = conn.execute("SELECT id, kind, text FROM work_blockers WHERE item_id = ? AND cleared_at IS NULL ORDER BY id", (item_id,))
    return [{"id": r["id"], "kind": r["kind"], "text": r["text"]} for r in rows]


def name_subtasks(found: Sequence[Mapping[str, Any]]) -> str:
    return ", ".join(f"{s['id']} '{s['title']}' ({s['state']})" for s in found)


def subtasks_sentence(found: Sequence[Mapping[str, Any]], wanted: str) -> str:
    if not found:
        return ""
    count = len(found)
    return f"{count} subtask{'' if count == 1 else 's'} {'is' if count == 1 else 'are'} not {wanted} yet: {name_subtasks(found)}"


def blockers_sentence(found: Sequence[Mapping[str, Any]]) -> str:
    if not found:
        return ""
    return "it still waits on " + "; ".join(str(b["text"] or b["kind"]) for b in found)


def _exempt(row: Mapping[str, Any], actor: str, act: Optional[Any], decided: Optional[Any]) -> bool:
    return actor != JOE or act is not None or decided is not None or row["lane"] == lane.SWARM or bool(row["swarm_ref"])


def check_tick(conn: sqlite3.Connection, row: Mapping[str, Any], new_state: str, actor: str, *, act: Optional[Any] = None,
               decided: Optional[Any] = None, now: float, before_id: Optional[int] = None) -> None:
    if new_state not in rules.APPROVED_STATES or row["state"] in rules.APPROVED_STATES or _exempt(row, actor, act, decided):
        return
    item_id = int(row["id"])
    stuck = subtasks_not_in(conn, item_id, READY_FOR_TICK, before_id=before_id)
    held = live_blockers(conn, item_id, now)
    if not stuck and not held:
        return
    reasons = [s for s in (subtasks_sentence(stuck, "done"), blockers_sentence(held)) if s]
    hints = [h for h, on in (("tick or delete each subtask first", stuck), ("clear the wait first", held)) if on]
    raise locked(stuck, held, f"cannot be ticked: {'; '.join(reasons)} ({', then '.join(hints)})")


def locked(stuck: Sequence[Mapping[str, Any]], held: Sequence[Mapping[str, Any]], message: str) -> TaskManagerLocked:
    reason = BOTH if stuck and held else (SUBTASKS if stuck else BLOCKERS)
    return TaskManagerLocked(reason, message, {SUBTASKS_KEY: [dict(s) for s in stuck], BLOCKERS_KEY: [dict(b) for b in held]})


def holding_subtasks(store: Any, item_id: int) -> List[Dict[str, Any]]:
    with closing(store._connect(False)) as conn:
        return subtasks_not_in(conn, item_id, tuple(s for s in rules.STATES if s not in blockers.HOLDING_STATES))


__all__ = ["BLOCKERS", "BOTH", "READY_FOR_REVIEW", "READY_FOR_TICK", "SUBTASKS", "blockers_sentence", "check_tick", "holding_subtasks",
           "live_blockers", "locked", "name_subtasks", "review_subtasks", "subtasks_not_in", "subtasks_sentence"]
