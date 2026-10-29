
from __future__ import annotations

import sqlite3
from typing import Mapping, Optional

from src.cplugs.huddle import rules, status_lines
from src.cplugs.huddle.rules import JOE, QUESTION, REPLY, TaskManagerForbidden, TaskManagerInvalid

INFO = "info"
ATTENTION = "attention"
ANSWER = "answer"
COMMENT = "comment"
REPLY_KINDS = (INFO, ATTENTION, ANSWER)
MESSAGE_KINDS = (QUESTION, REPLY, INFO, ATTENTION, ANSWER, COMMENT)
INFO_KINDS = (INFO, ANSWER)


READ_ONE_KINDS = (INFO, ANSWER, ATTENTION)


def unread_sql(kind: str) -> str:
    if kind not in READ_ONE_KINDS:
        raise TaskManagerInvalid(f"{kind} posts are not read one by one")
    if kind == INFO:
        names = ", ".join(f"'{k}'" for k in INFO_KINDS)
        return f"m.kind IN ({names}) AND m.seen = 0"
    return f"m.kind = '{kind}' AND m.seen = 0"


UNSEEN_WHERE = "attention_seq > seen_seq"


def resolve(kind: Optional[str], actor: str, status: str) -> str:
    rules.check_actor(actor)
    if kind is not None and kind not in MESSAGE_KINDS:
        raise TaskManagerInvalid(f"kind must be one of {', '.join(MESSAGE_KINDS)}")
    if actor == JOE:
        if kind not in (None, REPLY, COMMENT):
            raise TaskManagerForbidden("questions, info and attention are claude's; the owner replies or comments")
        return kind or REPLY
    if kind in (None, REPLY):
        return INFO
    return kind


def stamp_claude(conn: sqlite3.Connection, row: Mapping, kind: str, seq: int, notify: bool = False) -> None:
    if kind in INFO_KINDS and notify:
        conn.execute("UPDATE work_items SET info_seq = ?, attention_seq = ? WHERE id = ?", (seq, seq, row["id"]))
        return
    if kind in INFO_KINDS:
        conn.execute("UPDATE work_items SET info_seq = ? WHERE id = ?", (seq, row["id"]))
        return
    call = seq if kind == ATTENTION else None
    conn.execute("UPDATE work_items SET attention_seq = ?, call_seq = COALESCE(?, call_seq) WHERE id = ?",
                 (seq, call, row["id"]))


def needs_eyes(before: Optional[str], after: Optional[str]) -> bool:
    return after == rules.REVIEW and before != rules.REVIEW


def lights(row: Mapping) -> dict:
    keys = row.keys()
    info = row["info_unread"] if "info_unread" in keys else 0
    look = row["attention_unread"] if "attention_unread" in keys else 0
    return {"info_unread": info, "info_unseen": info > 0, "attention_unread": look, "attention_unseen": look > 0}


def read_post(conn: sqlite3.Connection, item_id: int, message_id: int) -> bool:
    row = conn.execute("SELECT kind, seen FROM work_messages WHERE id = ? AND item_id = ?", (message_id, item_id)).fetchone()
    if row is None or row[0] not in READ_ONE_KINDS:
        raise TaskManagerInvalid(f"message {message_id} is not an info or look post of item {item_id}")
    if row[1]:
        return False
    conn.execute("UPDATE work_messages SET seen = 1 WHERE id = ?", (message_id,))
    if conn.execute("SELECT 1 FROM work_messages WHERE item_id = ? AND author = 'claude' AND seen = 0 AND COALESCE(category, '') != ? LIMIT 1",
                    (item_id, status_lines.CATEGORY)).fetchone() is None:
        conn.execute("UPDATE work_items SET seen_seq = attention_seq WHERE id = ? AND seen_seq < attention_seq", (item_id,))
    return True


def acknowledge(conn: sqlite3.Connection, item_id: int, through: Optional[int] = None) -> bool:
    if through == 0:
        return False
    bound = None
    if through is not None:
        if through < 0 or (conn.execute("SELECT 1 FROM work_messages WHERE id = ? AND item_id = ?", (through, item_id)).fetchone() is None):
            raise TaskManagerInvalid(f"message {through} is not on item {item_id}")
        bound = through
    limit = "" if bound is None else " AND id <= ?"
    args = (item_id,) if bound is None else (item_id, bound)
    changed = conn.execute(f"UPDATE work_messages SET seen = 1 WHERE item_id = ? AND author = 'claude' AND seen = 0{limit}", args).rowcount
    first = None if bound is None else conn.execute(
        "SELECT MIN(seq) FROM work_messages WHERE item_id = ? AND author = 'claude' AND id > ? AND COALESCE(category, '') != ?",
        (item_id, bound, status_lines.CATEGORY)).fetchone()[0]
    attention = conn.execute("SELECT attention_seq FROM work_items WHERE id = ?", (item_id,)).fetchone()[0]
    reach = attention if first is None else min(attention, first - 1)
    changed += conn.execute("UPDATE work_items SET seen_seq = ? WHERE id = ? AND seen_seq < ?", (reach, item_id, reach)).rowcount
    return bool(changed)


def surfaces(kind: str) -> bool:
    return kind in (QUESTION, ATTENTION)


__all__ = ["ANSWER", "ATTENTION", "COMMENT", "INFO", "INFO_KINDS", "MESSAGE_KINDS",
           "READ_ONE_KINDS", "REPLY_KINDS", "UNSEEN_WHERE", "acknowledge", "lights", "read_post", "resolve",
           "needs_eyes", "stamp_claude", "surfaces", "unread_sql"]
