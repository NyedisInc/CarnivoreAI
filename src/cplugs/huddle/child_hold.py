
from __future__ import annotations

import sqlite3
from typing import Any, Dict, Mapping, Optional, Sequence

from src.cplugs.huddle import blockers, lane, review_lock, rules, waits
from src.cplugs.huddle.rules import TaskManagerInvalid

KIND = blockers.CHILDREN
FORK_ARG = "parent_waits"
_NOT_FOR_A_HOLD = ("expect_by", "wait_check", "extend_reason", "wait_until")
STOP_FIELD = "blocked"


def is_request(wait: Optional[Mapping[str, Any]]) -> bool:
    return wait is not None and wait.get("wait_kind") == KIND


def _refuse_unholdable(conn: sqlite3.Connection, row: Mapping[str, Any]) -> None:
    if row["lane"] == lane.SWARM or row["swarm_ref"]:
        raise TaskManagerInvalid("a Swarm-lane item or card does not wait on its forks; its board decides")
    if waits.live(conn, row["id"]) is not None:
        raise TaskManagerInvalid("this task already waits on something else (its wait): clear it first (task_manager_wait_update), then wait on its forked tasks")


def plan(conn: sqlite3.Connection, row: Mapping[str, Any], wait: Optional[Mapping[str, Any]], new_state: str, actor: str, act: Optional[Any]) -> bool:
    if wait is None or actor != rules.CLAUDE or act is not None or new_state != rules.WAITING:
        return False
    if not is_request(wait):
        if blockers.open_count(conn, row["id"]):
            raise TaskManagerInvalid("this task waits on its forked tasks; it cannot also park on something else. "
                                "They clear it when done, or clear it yourself with task_manager_wait_update")
        return False
    given = [name for name in _NOT_FOR_A_HOLD if wait.get(name)]
    if given:
        raise TaskManagerInvalid(f"waiting on its forked tasks takes no {', '.join(given)}: Carnivore clears it when they are done")
    _refuse_unholdable(conn, row)
    if not blockers.holding(conn, row["id"]):
        raise TaskManagerInvalid("none of this task's forked tasks is still open or waiting: there is nothing to wait on")
    return True


def check_fork(conn: sqlite3.Connection, parent: Mapping[str, Any], parent_state: Optional[str]) -> None:
    if parent_state is not None:
        raise TaskManagerInvalid("parent_waits sets the parent's state (waiting); leave parent_state out")
    if parent["state"] in rules.APPROVED_STATES:
        raise TaskManagerInvalid("a done task does not wait on its forks")
    _refuse_unholdable(conn, parent)


def stops(asked: Optional[str], item: Mapping[str, Any]) -> bool:
    return asked not in (None, rules.WAITING, rules.TODO) and item.get("state") == rules.WAITING and bool(item.get(blockers.FIELD))


def stop_answer(asked: Optional[str], item: Mapping[str, Any], holding: Sequence[Mapping[str, Any]] = ()) -> Dict[str, Any]:
    if not stops(asked, item):
        return {}
    found = list(item[blockers.FIELD])
    held = []
    if any(b.get("kind") == blockers.CHILDREN for b in found):
        count = sum(int(b.get("holding") or 0) for b in found)
        named = f": {review_lock.name_subtasks(holding)}" if holding else ""
        held.append(f"its forked tasks ({count} still open or waiting{named})")
    held.extend(str(b.get("text") or b.get("kind")) for b in found if b.get("kind") != blockers.CHILDREN)
    return {STOP_FIELD: f"held by {'; '.join(held)}: it stays waiting. Forked tasks clear it when done, "
                        "or clear it yourself with task_manager_wait_update result cleared"}
