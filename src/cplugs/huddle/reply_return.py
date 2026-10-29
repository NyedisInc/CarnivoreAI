
from __future__ import annotations

import sqlite3
from typing import Any, Mapping, Optional

from src.cplugs.huddle import actor_log, lineage, rules
from src.cplugs.huddle.cards import state_log

REPLIED = "joe replied"
BACK_TO_REVIEW, BACK_TO_DONE = "answered, back to review", "answered, back to done"
NOT_ANSWERED = "turn ended unanswered, back"
NOT_ANSWERED_TEXT = "the session's turn ended and it did not answer; this task went back to {state}. the owner's reply is still the last word here."
OWNER_REPLIED_HINT = ("the owner replied on these tasks and each is open again: answer a question with task_manager_reply, then return the task with "
                      "task_manager_update state review (a task he had ticked returns to done the same way, state done); for changes, work them and set review")


def replied_from(conn: sqlite3.Connection, row: Mapping[str, Any]) -> Optional[str]:
    if row["state"] != rules.OPEN:
        return None
    last = state_log.newest(conn, row["id"])
    if last is None or last["to_state"] != rules.OPEN or last["detail"] != REPLIED or last["by"] != actor_log.by_for(rules.JOE):
        return None
    return str(last["from_state"])


def answered_since_reply(conn: sqlite3.Connection, item_id: int) -> bool:
    reply = conn.execute("SELECT MAX(id) FROM work_messages WHERE item_id = ? AND author = ? AND kind = ?", (item_id, rules.JOE, rules.REPLY)).fetchone()[0]
    after = conn.execute("SELECT 1 FROM work_messages WHERE item_id = ? AND author = ? AND id > ? AND COALESCE(category, '') = '' LIMIT 1", (item_id, rules.CLAUDE, reply or 0)).fetchone()
    return after is not None


def awaiting_answer(conn: sqlite3.Connection, row: Mapping[str, Any]) -> bool:
    return replied_from(conn, row) in (rules.REVIEW, rules.DONE) and not answered_since_reply(conn, row["id"])


def unanswered_ids(conn: sqlite3.Connection, session_key: str) -> list:
    rows = conn.execute(
        "SELECT i.*, COALESCE(t.target, '') AS tell_target FROM work_items i JOIN work_sends t ON t.list_key = i.list_key "
        "WHERE i.deleted = 0 AND i.state = ? AND i.joe_seq <= t.cursor AND i.claude_working = 0 ORDER BY i.id", (rules.OPEN,)).fetchall()
    found = []
    for row in rows:
        told = row["tagged_session_key"] or row["owner_session_key"] or row["tell_target"]
        origin = replied_from(conn, row) if told == session_key else None
        if origin in (rules.REVIEW, rules.DONE) and not answered_since_reply(conn, row["id"]):
            found.append((int(row["id"]), origin))
    return found


def restore_to_done(conn: sqlite3.Connection, row: Mapping[str, Any], actor: str, state: Optional[str],
                    act: Optional[Any], decided: Optional[lineage.Decided]) -> Optional[lineage.Decided]:
    unanswered = decided is not None and decided.by == lineage.CARNIVORE and decided.detail == NOT_ANSWERED
    if (actor != rules.CLAUDE or state not in rules.APPROVED_STATES or act is not None or (decided is not None and not unanswered)
            or row["lane"] == "swarm" or replied_from(conn, row) != rules.DONE or not (unanswered or answered_since_reply(conn, row["id"]))):
        return None
    if unanswered:
        return decided
    return lineage.Decided(actor_log.by_for(actor), BACK_TO_DONE)


def answered_review(conn: sqlite3.Connection, row: Mapping[str, Any], actor: str, new_state: str,
                    act: Optional[Any], decided: Optional[lineage.Decided]) -> Optional[lineage.Decided]:
    if (actor != rules.CLAUDE or new_state != rules.REVIEW or act is not None or decided is not None
            or replied_from(conn, row) not in (rules.REVIEW, rules.DONE) or not answered_since_reply(conn, row["id"])):
        return None
    return lineage.Decided(actor_log.by_for(actor), BACK_TO_REVIEW)
