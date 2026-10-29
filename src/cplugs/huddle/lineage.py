
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, NamedTuple, Optional

from src.cplugs.huddle import actor_log, rules, status_lines
from src.cplugs.huddle.cards import state_log

BORN = "born"
CARNIVORE = "carnivore"
SUPERSEDED, CAUSE_GONE, SWARM_REFUSED = "superseded", "cause_gone", "swarm_refused"


class Decided(NamedTuple):

    by: str
    detail: str


def decided_by(actor: str, act: Optional[Any]) -> str:
    return act.by if act is not None else actor_log.by_for(actor)


def record(conn: sqlite3.Connection, item_id: int, list_key: str, from_state: str, to_state: str, *, by: str, now: float, detail: str = "") -> None:
    state_log.write(conn, item_id, list_key, from_state, to_state, by=by, now=now, detail=detail)
    status_lines.post(conn, item_id, from_state, to_state, by=by, now=now, detail=detail)


def record_move(conn: sqlite3.Connection, row: Any, new_state: str, actor: str, now: float, act: Optional[Any],
                decided: Optional[Decided] = None) -> None:
    if new_state == row["state"]:
        return
    if decided is not None:
        by, detail = decided.by, decided.detail
    else:
        by, detail = decided_by(actor, act), act.op if act is not None else ""
    record(conn, row["id"], row["list_key"], row["state"], new_state, by=by, now=now, detail=detail)


def record_birth(conn: sqlite3.Connection, item_id: int, list_key: str, state: str, actor: str, now: float, created_key: str = "") -> None:
    by = created_key if created_key and created_key != rules.OWNER_KEY else decided_by(actor, None)
    record(conn, item_id, list_key, "", state, by=by, now=now, detail=BORN)


def for_item(conn: sqlite3.Connection, item_id: int) -> List[Dict[str, Any]]:
    return state_log.for_item(conn, item_id)
