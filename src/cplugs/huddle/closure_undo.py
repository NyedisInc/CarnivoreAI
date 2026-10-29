
from __future__ import annotations

from contextlib import closing
from typing import Any, Dict, Optional

import structlog

from src.cplugs.huddle import actor_log, closures, corrections, lineage, rules, sends
from src.cplugs.huddle.cards import flow
from src.cplugs.huddle.moves import is_swarm_lane
from src.cplugs.huddle.rules import JOE, TaskManagerNotAllowed, TaskManagerStale
from src.cplugs.huddle.wire import MSG_COLS, item_dict, message_dict

logger = structlog.get_logger()

UNDO_DETAIL = {closures.COMPLETED: "undo completion", closures.CANCELLED: "undo cancellation"}
UNDO_TEXT = {closures.COMPLETED: corrections.COMPLETION_WITHDRAWN, closures.CANCELLED: corrections.CANCELLATION_WITHDRAWN}
RESTORABLE = (rules.OPEN, rules.REVIEW, rules.TODO)
MAX_NOTE = 500


def _insert_correction(store: Any, conn: Any, item_id: int, seq: int, text: str, parts: str) -> Dict[str, Any]:
    cur = conn.execute(
        "INSERT INTO work_messages (item_id, author, kind, text, created_at, seq, author_key, parts, seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)",
        (item_id, JOE, corrections.KIND, text, store._clock(), seq, rules.OWNER_KEY, parts))
    conn.execute("UPDATE work_items SET seq = ? WHERE id = ?", (seq, item_id))
    sends.stamp_joe(conn, [item_id], seq)
    return message_dict(conn.execute(f"SELECT {MSG_COLS} FROM work_messages WHERE id = ?", (cur.lastrowid,)).fetchone())


def undo_completion(store: Any, item_id: int, expected_revision: int) -> Dict[str, Any]:
    with store._immediate() as conn:
        row = store._row(conn, item_id)
        if expected_revision != row["revision"]:
            raise TaskManagerStale("the task changed since you read it", current=item_dict(row))
        if is_swarm_lane(row):
            raise TaskManagerNotAllowed("swarm_card", "a Swarm card is closed by the Swarm; it has no completion to withdraw")
        closure = closures.closure_of(conn, item_id)
        if closure is None:
            raise TaskManagerNotAllowed("not_closed", "the task is not closed, so there is nothing to withdraw")
        if not closure["known"] or not closure["latest"]:
            raise TaskManagerNotAllowed("moved", "the task moved after it was closed; reopen it instead")
        prior = closure["from_state"] if closure["from_state"] in RESTORABLE else rules.OPEN
        now = store._clock()
        flow.on_state_write(conn, row, prior, JOE, now, None, working=False,
                            decided=lineage.Decided(actor_log.by_for(JOE), UNDO_DETAIL[closure["outcome"]]))
        seq = store._next_seq(conn)
        conn.execute("UPDATE work_items SET state = ?, claude_done = ?, claude_working = 0, claude_working_by = '', updated_at = ?, revision = revision + 1, seq = ? WHERE id = ?",
                     (prior, int(prior == rules.REVIEW), now, seq, item_id))
        message = _insert_correction(store, conn, item_id, seq, UNDO_TEXT[closure["outcome"]],
                                     corrections.build(closure["outcome"], closure["id"], closure["closed_at"], closure["closed_by"], prior))
        list_key = row["list_key"]
    store._commit_notify(list_key)
    store._acted_on(item_id)
    logger.info("task_manager_completion_undone", item=item_id, outcome=closure["outcome"], restored=prior)
    return {"item": store.item(item_id), "message": message}


def cancel_task(store: Any, item_id: int, expected_revision: int, note: Optional[str] = None) -> Dict[str, Any]:
    text = corrections.TASK_CANCELLED
    if note and note.strip():
        text = f"{text}: {rules.clean_text(note, 'note', MAX_NOTE)}"
    with closing(store._read_connection()) as conn:
        row = store._row(conn, item_id)
    if is_swarm_lane(row):
        raise TaskManagerNotAllowed("swarm_card", "a Swarm card is closed by the Swarm")
    if row["state"] in rules.APPROVED_STATES:
        raise TaskManagerNotAllowed("already_closed", "the task is already closed")
    store.update(item_id, actor=JOE, state=rules.DONE, expected_revision=expected_revision,
                 decided=lineage.Decided(actor_log.by_for(JOE), closures.CANCELLED_DETAIL))
    with store._immediate() as conn:
        closure = closures.closure_of(conn, item_id)
        message = _insert_correction(store, conn, item_id, store._next_seq(conn), text,
                                     corrections.build(closures.CANCELLED, closure["id"], closure["closed_at"], closure["closed_by"]))
    store._commit_notify(row["list_key"])
    logger.info("task_manager_task_cancelled", item=item_id)
    return {"item": store.item(item_id), "message": message}
