
from __future__ import annotations

import sqlite3
from typing import Mapping, NamedTuple, Optional, Tuple

from src.cplugs.huddle import lifecycle, lineage, moves, rules
from src.cplugs.huddle.roles import claims
from src.cplugs.huddle.rules import CLAUDE, TaskManagerForbidden, TaskManagerInvalid

FIELD = "forked_from"
TITLE_FIELD = "forked_from_title"
SELECT_COLS = ("forked_from, (SELECT COALESCE(NULLIF(p.title, ''), p.text) FROM work_items p WHERE p.id = work_items.forked_from) "
               "AS forked_from_title")
MAX_NAME = 80


NEW_ITEM = {"state": rules.OPEN, "note": "", "claude_done": 0}


class StateChange(NamedTuple):

    state: str
    claude_done: bool
    working: bool


def wire(row: Mapping) -> dict:
    parent = row[FIELD]
    out: dict = {FIELD: parent}
    if parent is not None:
        out[TITLE_FIELD] = row[TITLE_FIELD]
    return out


def plan_state(actor: str, row: Mapping, state: Optional[str]) -> Optional[StateChange]:
    state = rules.canonical_state(state)
    if state is None:
        return None
    working = state == lifecycle.WORKING
    if working and actor != CLAUDE:
        raise TaskManagerInvalid(f"state must be one of {', '.join(rules.STATES)}")
    target = rules.OPEN if working else state
    claude_done = bool(row["claude_done"])
    if actor == CLAUDE:
        claude_done = target == rules.REVIEW
    elif target == rules.OPEN:
        claude_done = False
    new_state = rules.next_state(actor, row["state"], approve=None, state=target, note=row["note"], claude_done=claude_done)
    return StateChange(new_state, claude_done, working)


def gate(conn: sqlite3.Connection, parent: Mapping, change: Optional[StateChange], actor: str,
         now: float) -> Tuple[Optional[StateChange], Optional[lineage.Decided]]:
    if change is None:
        return None, None
    state, decided = moves.checkpoint(conn, parent, change.state, actor, None, None, now)
    if not moves.was_stopped(decided):
        return change, None
    moves.record_stop(conn, parent, state, decided, now)
    if state == parent["state"]:
        return None, decided
    return StateChange(state, False, False), decided


def check_parent(actor: str, parent: Mapping, parent_state: Optional[str]) -> None:
    rules.check_not_swarm_card(actor, parent["swarm_ref"])
    if parent_state is not None and parent["swarm_ref"]:
        raise TaskManagerForbidden("a Swarm card's state is decided on its card; fork it without a parent state")


def write_state(conn: sqlite3.Connection, item_id: int, change: StateChange, *, seq: int, now: float, claimant: str) -> None:
    conn.execute(
        "UPDATE work_items SET state = ?, claude_done = ?, updated_at = ?, revision = revision + 1, seq = ?, "
        f"claude_working = (? AND {claims.NOT_SWARM_LANE_SQL}), claude_working_by = CASE WHEN ? AND {claims.NOT_SWARM_LANE_SQL} THEN ? ELSE '' END, "
        "claude_read_seq = MAX(claude_read_seq, CASE WHEN ? THEN joe_seq ELSE 0 END) WHERE id = ?",
        (change.state, int(change.claude_done), now, seq, int(change.working), int(change.working), claimant, int(change.working), item_id))
    if change.state in rules.APPROVED_STATES:
        conn.execute("UPDATE work_items SET flag_color = NULL, flag_reason = NULL WHERE id = ?", (item_id,))


def name_of(row: Mapping) -> str:
    name = (row["title"] or row["text"] or "").strip().replace("\n", " ")
    return name if len(name) <= MAX_NAME else name[:MAX_NAME - 1].rstrip() + "..."


def post_info(conn: sqlite3.Connection, item_id: int, text: str, *, seq: int, now: float) -> None:
    conn.execute("INSERT INTO work_messages (item_id, author, kind, text, created_at, seq, author_key, seen) VALUES (?, ?, 'info', ?, ?, ?, 'system', 1)",
                 (item_id, CLAUDE, text, now, seq))


def default_group(parent: Mapping, list_key: str) -> Optional[int]:
    return parent["group_id"] if list_key == parent["list_key"] else None
