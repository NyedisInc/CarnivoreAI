
from __future__ import annotations

import sqlite3
import time
from typing import Collection, Iterable, Mapping, Optional, Sequence, Set, Tuple

from src.cplugs.huddle import item_owner, review, rules, sends, triggers
from src.cplugs.huddle.cards import flow
from src.cplugs.huddle.roles import claims

OPEN = "open"
QUESTION = "question"
WAITING_TO_SEND = "waiting_to_send"
WORKING = "working"
PICKUP_OP = "pickup"
WAITING = rules.WAITING
REVIEW = "review"
TODO = rules.TODO
SCHEDULED = "scheduled"
STATUSES = (rules.DONE, QUESTION, WAITING_TO_SEND, REVIEW, WAITING, WORKING, SCHEDULED, OPEN, TODO)

DONE = "done"
SECTIONS = (QUESTION, REVIEW, WAITING, WORKING, WAITING_TO_SEND, SCHEDULED, OPEN, TODO, DONE)
_SECTION_RANK = {name: rank for rank, name in enumerate(SECTIONS)}

VIEW_STATUS = "status"
VIEW_AREA = "area"


def section_of(item_status: str) -> str:
    return DONE if item_status in rules.APPROVED_STATES else item_status


NEEDS_YOU_STATUSES = (QUESTION,)


NEEDS_YOU_LOOK_ACTIONS = (review.ANSWER, review.TICK, review.PUSH)




def needs_action(item_status: str, review_action: Optional[str] = None, look_action: Optional[str] = None,
                 answer_unread: bool = False, info_pending: bool = False) -> Optional[str]:
    if item_status in rules.APPROVED_STATES:
        return None
    if item_status == QUESTION:
        return review.ANSWER
    if item_status == REVIEW:
        return None
    if answer_unread or info_pending:
        return review.READ
    return look_action if look_action in NEEDS_YOU_LOOK_ACTIONS else None


def row_action(row: Mapping, item_status: str) -> Optional[str]:
    keys = row.keys()
    return needs_action(item_status, row["review_action"] if "review_action" in keys else None,
                        review.look_action(row["look_parts"] if "look_parts" in keys else None),
                        bool(row["answer_unread"]) if "answer_unread" in keys else False,
                        bool(row["info_pending"]) if "info_pending" in keys else False)


JOE_TURN = "joe_turn"
JOE_OUTBOX = "joe_outbox"
AGENT_ACTIVE = "agent_active"
AGENT_IDLE = "agent_idle"
EXTERNAL_WAIT = "external_wait"
PARKED = "parked"
DONE_POSITION = "done"
POSITIONS = (JOE_TURN, JOE_OUTBOX, AGENT_ACTIVE, AGENT_IDLE, EXTERNAL_WAIT, PARKED, DONE_POSITION)
SESSION_BUSY = ("working", "working_subagent")
SESSION_BLOCKED = ("question", "notice")


def position(row: Mapping, item_status: str, *, list_held: bool = False, session_state: Optional[str] = None,
             idle: bool = False) -> str:
    if item_status in rules.APPROVED_STATES:
        return DONE_POSITION
    if item_status == WAITING_TO_SEND or (item_status == TODO and note_waiting(row, item_status)):
        return JOE_OUTBOX
    if item_status in (QUESTION, REVIEW) or row_action(row, item_status):
        return JOE_TURN
    if item_status == TODO:
        return PARKED
    keys = row.keys()
    swarm_ref = row["swarm_ref"] if "swarm_ref" in keys else ""
    if (item_status == WAITING or item_status == SCHEDULED or triggers.is_pending(row) or (row["kind"] == "waiting")
            or (_col(row, "card_queued") and not _col(row, "owner_session_key"))
            or (row["card_holder"] if "card_holder" in keys else None) is not None
            or swarm_ref not in rules.NOT_A_CARD_REFS or list_held or session_state in SESSION_BLOCKED):
        return EXTERNAL_WAIT
    if session_state in SESSION_BUSY or not idle:
        return AGENT_ACTIVE
    return AGENT_IDLE




def blocks_schedule(row: Mapping, item_status: str) -> bool:
    if position(row, item_status) != JOE_TURN:
        return False
    return item_status in (QUESTION, REVIEW) or row_action(row, item_status) != review.READ

def needs_you(item_status: str, review_action: Optional[str] = None, look_action: Optional[str] = None,
              answer_unread: bool = False) -> bool:
    return needs_action(item_status, review_action, look_action, answer_unread) is not None


def section_rank(item_status: str) -> int:
    return _SECTION_RANK.get(section_of(item_status), _SECTION_RANK[OPEN])


_READ_CLAIM_WHERE = (
    "claude_working = 1 AND claude_working_by != '' "
    "AND EXISTS (SELECT 1 FROM work_write_actors p WHERE p.item_id = work_items.id AND p.actor_key = work_items.claude_working_by AND p.op = 'pickup' "
    "AND NOT EXISTS (SELECT 1 FROM work_write_actors u WHERE u.item_id = work_items.id AND u.actor_key = work_items.claude_working_by "
    "AND u.op IN ('update', 'fork') AND u.id > p.id))"
)


def sweep_read_claims(conn: sqlite3.Connection) -> Tuple[list, Set[str]]:
    rows = conn.execute(f"SELECT id, list_key FROM work_items WHERE {_READ_CLAIM_WHERE} ORDER BY id").fetchall()
    if not rows:
        return [], set()
    marks = ",".join("?" * len(rows))
    conn.execute(
        "UPDATE work_items SET claude_working = 0, claude_working_by = '', "
        f"{item_owner.COLUMN} = CASE WHEN {item_owner.COLUMN} = claude_working_by THEN '' ELSE {item_owner.COLUMN} END "
        f"WHERE id IN ({marks})", [r[0] for r in rows])
    return [r[0] for r in rows], {r[1] for r in rows}


_READ_OWNER_WHERE = (
    f"{item_owner.COLUMN} != '' AND deleted = 0 "
    f"AND NOT (claude_working = 1 AND claude_working_by = {item_owner.COLUMN}) "
    f"AND EXISTS (SELECT 1 FROM work_write_actors p WHERE p.item_id = work_items.id AND p.actor_key = work_items.{item_owner.COLUMN} AND p.op = 'pickup') "
    f"AND NOT EXISTS (SELECT 1 FROM work_write_actors u WHERE u.item_id = work_items.id AND u.actor_key = work_items.{item_owner.COLUMN} AND u.op != 'pickup')"
)


def sweep_read_owners(conn: sqlite3.Connection) -> Tuple[list, Set[str], dict]:
    rows = conn.execute(f"SELECT id, list_key, {item_owner.COLUMN} FROM work_items WHERE {_READ_OWNER_WHERE} ORDER BY id").fetchall()
    if not rows:
        return [], set(), {}
    item_owner.clear(conn, [r[0] for r in rows])
    return [r[0] for r in rows], {r[1] for r in rows}, {r[0]: r[2] for r in rows}


def sent_seq(row: Mapping) -> int:
    sent = max(row["claude_read_seq"], _col(row, "told_seq"))
    return sent if sends.sendable(row) else max(sent, row["joe_seq"])


def _col(row: Mapping, name: str) -> int:
    return (row[name] if name in row.keys() else 0) or 0


def status(row: Mapping, asking: bool) -> str:
    state = row["state"]
    sent = sent_seq(row)
    if state in rules.APPROVED_STATES:
        return WAITING_TO_SEND if row["joe_seq"] > sent else state
    if state == rules.TODO:
        return TODO
    if asking or (row["kind"] == rules.QUESTION and row["created_by"] == rules.CLAUDE and not row["joe_seq"]):
        return QUESTION
    if state == rules.OPEN and not row["claude_working"] and triggers.is_pending(row):
        return SCHEDULED
    if row["joe_seq"] > sent:
        return WAITING_TO_SEND
    if state == rules.REVIEW:
        return REVIEW
    if state == rules.WAITING:
        return WAITING
    if row["claude_working"]:
        return WORKING
    return OPEN


def note_waiting(row: Mapping, item_status: str) -> bool:
    return item_status in (TODO, QUESTION) and row["joe_seq"] > sent_seq(row)


def asking_ids(conn: sqlite3.Connection, item_ids: Sequence[int]) -> Set[int]:
    if not item_ids:
        return set()
    marks = ",".join("?" * len(item_ids))
    return {r[0] for r in conn.execute(
        f"SELECT DISTINCT item_id FROM work_messages WHERE kind = 'question' AND answered = 0 AND item_id IN ({marks})",
        list(item_ids))}


_BEHIND_WHERE = "id = ? AND deleted = 0 AND claude_read_seq < MIN(joe_seq, ?)"


def any_behind(conn: sqlite3.Connection, seen: Iterable[Tuple[int, int]]) -> bool:
    return any(conn.execute(f"SELECT 1 FROM work_items WHERE {_BEHIND_WHERE}", (item_id, seq)).fetchone() for item_id, seq in seen)


def record_read(conn: sqlite3.Connection, seen: Iterable[Tuple[int, int]]) -> Set[str]:
    moved: Set[str] = set()
    for item_id, seq in seen:
        row = conn.execute(f"SELECT list_key, joe_seq FROM work_items WHERE {_BEHIND_WHERE}", (item_id, seq)).fetchone()
        if row is None:
            continue
        list_key, joe_seq = row
        conn.execute("UPDATE work_items SET claude_read_seq = ? WHERE id = ?", (min(joe_seq, seq), item_id))
        moved.add(list_key)
    return moved


def claim(conn: sqlite3.Connection, item_id: int, holder: str) -> bool:
    return bool(conn.execute(f"UPDATE work_items SET claude_working = 1, claude_working_by = ? WHERE id = ? AND {flow.UNHELD_SQL} "
                             f"AND {claims.NOT_SWARM_LANE_SQL} AND {item_owner.COLUMN} IN ('', ?)", (holder, item_id, holder)).rowcount)


def end_claims_of(conn: sqlite3.Connection, holder: str) -> Set[str]:
    if not holder:
        return set()
    keys = {r[0] for r in conn.execute("SELECT DISTINCT list_key FROM work_items WHERE claude_working = 1 AND claude_working_by = ?", (holder,))}
    conn.execute("UPDATE work_items SET claude_working = 0, claude_working_by = '' WHERE claude_working = 1 AND claude_working_by = ?", (holder,))
    return keys


def end_claim(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute("UPDATE work_items SET claude_working = 0, claude_working_by = '' WHERE id = ?", (item_id,))


def needs_you_counts(rows: Iterable[Mapping], asking: Set[int]) -> dict:
    out: dict = {}
    for row in rows:
        if row_action(row, status(row, row["id"] in asking)):
            out[row["list_key"]] = out.get(row["list_key"], 0) + 1
    return out


def attention_counts(rows: Iterable[Mapping], asking: Set[int]) -> dict:
    out: dict = {}
    for row in rows:
        if status(row, row["id"] in asking) in (QUESTION, REVIEW):
            out[row["list_key"]] = out.get(row["list_key"], 0) + 1
    return out


BADGE_STATUSES = (QUESTION, REVIEW, OPEN, WORKING, WAITING, SCHEDULED)


def status_counts(rows: Iterable[Mapping], asking: Set[int]) -> dict:
    out: dict = {}
    for row in rows:
        item_status = status(row, row["id"] in asking)
        if item_status in BADGE_STATUSES:
            per_list = out.setdefault(row["list_key"], {})
            per_list[item_status] = per_list.get(item_status, 0) + 1
    return out


def waiting_counts(rows: Iterable[Mapping], asking: Set[int]) -> dict:
    out: dict = {}
    for row in rows:
        item_status = status(row, row["id"] in asking)
        if item_status == WAITING_TO_SEND or (item_status == QUESTION and note_waiting(row, item_status)):
            out[row["list_key"]] = out.get(row["list_key"], 0) + 1
    return out
