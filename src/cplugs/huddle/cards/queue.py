
from __future__ import annotations

import sqlite3
from typing import Optional

from src.cplugs.huddle import groups, rules
from src.cplugs.huddle.cards import flow, policy, projection
from src.cplugs.huddle.wire import ITEM_COLS
from src.cplugs.sdk.cards import CardRefused

MAX_REASON_CHARS = 500


def _waiting_todo(row: sqlite3.Row) -> bool:
    return (row["state"] == rules.OPEN and projection.column(row) == projection.TODO and row["card_paused_mode"] == ""
            and row["card_archived_at"] is None)


def top_todo(conn: sqlite3.Connection, list_key: str) -> Optional[int]:
    for row in conn.execute(f"SELECT {ITEM_COLS} FROM work_items WHERE list_key = ? AND deleted = 0 {groups.ITEM_ORDER}", (list_key,)):
        if projection.card_shaped(row) and _waiting_todo(row):
            return row["id"]
    return None


def queue(conn: sqlite3.Connection, card_id: int, *, by: str, reason: str, now: float) -> flow.FlowResult:
    row = flow._row(conn, card_id)
    if row["state"] != rules.OPEN or projection.column(row) != projection.TODO:
        raise CardRefused("not_todo", "only an open todo card is queued (this one is already in the work or past it)")
    if row["card_paused_mode"]:
        raise CardRefused("paused", "this card is paused")
    if row["card_archived_at"] is not None:
        raise CardRefused("archived", "this card is archived")
    if len(reason) > MAX_REASON_CHARS:
        raise CardRefused("bad_card", f"the reason is at most {MAX_REASON_CHARS} characters")
    top = top_todo(conn, row["list_key"])
    out_of_order = top is not None and top != card_id
    if out_of_order and not reason and by.startswith("agent:"):
        raise CardRefused("not_top", f"card #{top} is the top todo card and goes first; queue it, or give a reason for taking this one out of order")
    flow._set(conn, card_id, {"card_queued": 1, "card_auto_promote": 0})
    policy.request_deal(conn, row["list_key"], "queued", card_id, now)
    who = "the owner" if by == "owner" else f"agent {by.split(':', 1)[1]}" if by.startswith("agent:") else by
    detail = f"queued by {who}" + (f", ahead of #{top}" if out_of_order else ", the top todo card") + (f": {reason}" if reason else "")
    flow._event(conn, card_id, "moved", list_key=row["list_key"], by=by, now=now, from_col=projection.TODO, to_col=projection.IN_PROGRESS,
                detail=detail[:MAX_REASON_CHARS])
    flow._touch(conn, card_id, by, now, mark=False)
    return flow._done(conn, card_id, [])


def top_queued(conn: sqlite3.Connection, list_key: str) -> Optional[int]:
    for row in conn.execute(f"SELECT {ITEM_COLS} FROM work_items WHERE list_key = ? AND deleted = 0 {groups.ITEM_ORDER}", (list_key,)):
        if projection.card_shaped(row) and projection.dealable(row):
            return row["id"]
    return None


def deal(conn: sqlite3.Connection, card_id: int, *, agent_id: int, by: str, slot_ok: bool, now: float, commit: bool,
         reason: str = "") -> flow.FlowResult:
    if len(reason) > MAX_REASON_CHARS:
        raise CardRefused("bad_card", f"the reason is at most {MAX_REASON_CHARS} characters")
    row = flow._row(conn, card_id)
    top = top_queued(conn, row["list_key"]) if by.startswith("agent:") and not commit and row["card_pin_agent"] is None else None
    out_of_order = top is not None and top != card_id
    if out_of_order and not reason:
        raise CardRefused("not_top", f"card #{top} is the top queued card and is dealt first; deal it, or give a reason for dealing this one out of order")
    result = flow.deal(conn, card_id, agent_id=agent_id, by=by, slot_ok=slot_ok, now=now, commit=commit)
    if reason:
        flow._event(conn, card_id, "noted", list_key=row["list_key"], by=by, now=now,
                    detail=(f"dealt ahead of #{top}: " if out_of_order else f"dealt to agent {agent_id}: ") + reason)
    return result
