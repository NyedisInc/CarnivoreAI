
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple

import structlog

from src.core.work import tables
from src.cplugs.huddle import actor_log, blockers, lane, lineage, rules, triggers
from src.cplugs.huddle.cards import state_log

logger = structlog.get_logger()

BORN_STATES = (rules.OPEN, rules.TODO)
_BLOCK_EXEMPT = (rules.WAITING, rules.TODO)
BLOCKED, REPEAT_TICK, SUPERSEDED = "blocked", "repeat_tick", "superseded"


def born_state(value: object) -> str:
    state = rules.canonical_state(value) if value not in (None, "") else rules.OPEN
    if state not in BORN_STATES:
        raise rules.TaskManagerInvalid(f"an item is born {' or '.join(BORN_STATES)}, not {value!r}; move it after adding")
    return str(state)


def is_swarm_lane(row: Mapping[str, Any]) -> bool:
    return row["lane"] == lane.SWARM


def checkpoint(conn: sqlite3.Connection, row: Mapping[str, Any], new_state: str, actor: str, act: Optional[Any],
               decided: Optional[lineage.Decided], now: float) -> Tuple[str, Optional[lineage.Decided]]:
    if (actor != rules.CLAUDE or act is not None or decided is not None or is_swarm_lane(row)
            or new_state == row["state"] or new_state in _BLOCK_EXEMPT or not blockers.is_held(conn, row["id"], now)):
        return new_state, decided
    return rules.WAITING, lineage.Decided(lineage.CARNIVORE, BLOCKED)


def was_stopped(decided: Optional[lineage.Decided]) -> bool:
    return decided is not None and decided.by == lineage.CARNIVORE and decided.detail == BLOCKED


def record_stop(conn: sqlite3.Connection, row: Mapping[str, Any], new_state: str, decided: Optional[lineage.Decided], now: float) -> None:
    if was_stopped(decided) and new_state == row["state"]:
        lineage.record(conn, row["id"], row["list_key"], row["state"], new_state, by=lineage.CARNIVORE, now=now, detail=BLOCKED)


def repeating(row: Mapping[str, Any]) -> bool:
    return triggers.rule_of(row["trigger_repeat"], row["id"]) is not None


def repeat_tick(row: Mapping[str, Any], actor: str, new_state: str, decided: Optional[lineage.Decided],
                act: Optional[Any]) -> Tuple[str, Optional[lineage.Decided]]:
    if (actor != rules.JOE or act is not None or decided is not None or new_state not in rules.APPROVED_STATES
            or is_swarm_lane(row) or not repeating(row)):
        return new_state, decided
    return rules.OPEN, lineage.Decided(actor_log.by_for(actor), REPEAT_TICK)


def reply_reopens(row: Mapping[str, Any], *, wait_on_owner: bool = False) -> bool:
    if row["state"] == rules.WAITING:
        return wait_on_owner
    if row["state"] == rules.REVIEW:
        return True
    return row["state"] in rules.APPROVED_STATES and not is_swarm_lane(row)


def supersede_questions(conn: sqlite3.Connection, item_id: int, keep_id: int, seq: int) -> int:
    return conn.execute("UPDATE work_messages SET answered = ?, seq = ? WHERE item_id = ? AND kind = 'question' AND answered = 0 AND id != ?",
                        (rules.ANSWERED_SUPERSEDED, seq, item_id, keep_id)).rowcount


def purge(conn: sqlite3.Connection, item_id: int) -> None:
    for table in (tables.MESSAGES, tables.ITEM_LINEAGE, tables.BLOCKERS, tables.WRITE_ACTORS, tables.ITEM_NUDGES, tables.ITEM_WAITS):
        conn.execute(f"DELETE FROM {table} WHERE item_id = ?", (item_id,))
    state_log.purge(conn, item_id)
    conn.execute("UPDATE work_items SET text = '', note = '', title = NULL, perceived_ask = NULL, review_description = NULL, review_summary = NULL, "
                 "review_link = NULL, review_where = NULL, flag_color = NULL, flag_reason = NULL WHERE id = ?", (item_id,))


def remove_folder(folder: Path) -> bool:
    if not folder.is_dir():
        return False
    try:
        shutil.rmtree(folder)
    except OSError as exc:
        logger.warning("task_manager_item_folder_left", folder=str(folder), error=str(exc)[:200])
        return False
    return True
