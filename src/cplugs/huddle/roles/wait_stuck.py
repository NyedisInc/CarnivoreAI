
from __future__ import annotations

import sqlite3
from typing import Any, Dict, Mapping, Optional

from src.cplugs.huddle import actor_log, lineage, rules, triggers, wait_copy, waits
from src.cplugs.huddle.cards import flow
from src.cplugs.huddle.rules import TaskManagerInvalid

HANDLE, DROP, CHECK, UNTIL = "handle", "drop", "check", "until"
PUSH, LONGER = "push", "wait"
OPTIONS = (HANDLE, DROP, CHECK, UNTIL)
LABELS = {HANDLE: "i'll handle it", DROP: "drop it", CHECK: "check it now", UNTIL: "give it until..."}
TELLS_AGENT = (CHECK, PUSH)
UNTIL_ID = "q2"
UNTIL_QUESTION: Dict[str, Any] = {"id": UNTIL_ID, "type": "datetime", "prompt": "until when? (only for give it until)", "required": False}

DETAILS = {HANDLE: "wait_handle", DROP: "wait_drop", CHECK: "wait_push", PUSH: "wait_push", UNTIL: "wait_until"}


def prompt(what: str, set_at: float) -> str:
    return wait_copy.stuck_prompt(what, set_at)


def owner_time(text: str, now: float) -> str:
    if not text.strip():
        raise TaskManagerInvalid("give it until needs a time: pick when")
    triggers.parse_fire_at(text, now)
    return text.strip()


def _move(conn: sqlite3.Connection, item: Mapping[str, Any], target: str, detail: str, now: float) -> None:
    flow.on_state_write(conn, item, target, rules.JOE, now, None, working=False, decided=lineage.Decided(actor_log.by_for(rules.JOE), detail))
    conn.execute("UPDATE work_items SET state = ?, claude_done = 0, claude_working = 0, claude_working_by = '', revision = revision + 1 WHERE id = ?",
                 (target, item["id"]))


def apply_choice(conn: sqlite3.Connection, item: Mapping[str, Any], choice: str, answers: Optional[Mapping[str, Any]], now: float) -> str:
    if item["state"] != rules.WAITING:
        return choice
    if choice == LONGER:
        waits.grant_longer(conn, item["id"], now)
        conn.execute("UPDATE work_items SET revision = revision + 1 WHERE id = ?", (item["id"],))
        return choice
    stamp = owner_time(((answers or {}).get(UNTIL_ID) or {}).get("text", ""), now) if choice == UNTIL else ""
    waits.settle(conn, item["id"])
    target = {CHECK: rules.OPEN, PUSH: rules.OPEN}.get(choice, rules.TODO)
    _move(conn, item, target, DETAILS.get(choice, DETAILS[DROP]), now)
    if choice == UNTIL:
        change = triggers.plan(conn, item["id"], rules.TODO, stamp, None, None, now)
        if change is not None:
            triggers.apply(conn, item["id"], change, now)
    return choice
