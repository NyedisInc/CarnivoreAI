
from __future__ import annotations

import dataclasses
from contextlib import closing
from typing import Any, Dict, List, Mapping, Optional

import structlog

from src.cplugs.huddle import lane, rules
from src.cplugs.huddle.cards import flow, reads
from src.cplugs.huddle.cards.flow import CardAct, Effect
from src.cplugs.huddle.rules import CLAUDE, JOE
from src.cplugs.huddle.wire import ITEM_COLS
from src.cplugs.sdk.cards import CardRefused

logger = structlog.get_logger()

_MAX_MERGED = 4000


def _answer(store: Any, card_id: int, effects: List[Effect], data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    with closing(store._read_connection()) as conn:
        card = reads.one(conn, card_id)
    return {"card": card, "effects": [dataclasses.asdict(e) for e in effects], "data": data or {}}


def finish(store: Any, card_id: int, args: Mapping[str, Any], by: str) -> Dict[str, Any]:
    act = CardAct("finish", by, {"result": args["result"], "report_id": args.get("report_id")})
    fields: Dict[str, object] = {"review_description": args["how_to_validate"]}
    if args.get("validate_link"):
        fields["review_link"] = args["validate_link"]
    store.update(card_id, actor=CLAUDE, state=rules.REVIEW, review_fields=fields, act=act)
    return _answer(store, card_id, act.effects)


def _accepted_children(store: Any, card_id: int, *, swarm_only: bool = False) -> List[int]:
    lane_sql = f" AND lane = '{lane.SWARM}'" if swarm_only else ""
    with closing(store._read_connection()) as conn:
        return [r["id"] for r in conn.execute(
            f"SELECT id FROM work_items WHERE {reads.CARD_WHERE} AND card_parent = ? AND card_accepted_at IS NOT NULL AND state IN (?, ?){lane_sql}",
            (card_id, rules.REVIEW, rules.WAITING))]


def done(store: Any, card_id: int, args: Mapping[str, Any], by: str) -> Dict[str, Any]:
    with closing(store._read_connection()) as conn:
        card = reads.one(conn, card_id)
    if card is None or card["column"] != "review":
        raise CardRefused("not_in_review" if card else "not_a_card", "that card is not in review" if card else "that item is not a card")
    act = CardAct("done", by, {"expect_pass": args.get("expect_pass")})
    store.update(card_id, actor=JOE, approve=True, expected_revision=args.get("expected_revision"), act=act)
    for child in _accepted_children(store, card_id, swarm_only=by == "auto_done"):
        store.update(child, actor=JOE, approve=True, act=CardAct("done", by))
    _rollup_due(store, card_id, act.effects)
    return _answer(store, card_id, act.effects)


def _rollup_due(store: Any, card_id: int, effects: List[Effect]) -> None:
    with closing(store._read_connection()) as conn:
        parent = conn.execute("SELECT card_parent FROM work_items WHERE id = ?", (card_id,)).fetchone()["card_parent"]
        if parent is not None and flow.rollup_due(conn, parent):
            effects.append(Effect("rollup", parent))


def set_column(store: Any, card_id: int, args: Mapping[str, Any], by: str) -> Dict[str, Any]:
    with closing(store._read_connection()) as conn:
        card = reads.one(conn, card_id)
    if card is None:
        raise CardRefused("not_a_card", "that item is not a card")
    target = args.get("column")
    if target == card["column"]:
        return _answer(store, card_id, [], {"changed": False})
    if target == "done" and card["column"] == "review":
        return done(store, card_id, {}, by)
    act = CardAct("set_column", by, {"queued": target == "in_progress"})
    if target == "done":
        store.update(card_id, actor=JOE, approve=True, act=act)
        _rollup_due(store, card_id, act.effects)
    elif target == "review":
        store.update(card_id, actor=JOE, state=rules.REVIEW, act=act)
    elif target in ("todo", "in_progress") and card["state"] != rules.OPEN:
        store.update(card_id, actor=JOE, state=rules.OPEN, act=act)
    else:
        raise CardRefused("bad_card", "column must be todo, in_progress, review or done")
    return _answer(store, card_id, act.effects)


def send_back(store: Any, card_id: int, args: Mapping[str, Any], by: str) -> Dict[str, Any]:
    note = args["note"]
    act = CardAct("send_back", by, {"note": note, "rehold": args.get("rehold")})
    posted = store.post(card_id, note, actor=JOE, author_key=rules.OWNER_KEY, act=act)
    ref = f"huddle:msg:{posted['message']['id']}"
    effects = act.effects + [Effect("learn", card_id, text=note, ref=ref)]
    return _answer(store, card_id, effects, {"message_ref": ref})


def reject(store: Any, card_id: int, args: Mapping[str, Any], by: str) -> Dict[str, Any]:
    act = CardAct("reject", by, {"rehold": args.get("rehold")})
    store.update(card_id, actor=CLAUDE, state=rules.OPEN, act=act)
    return _answer(store, card_id, act.effects)


def validation_fail(store: Any, card_id: int, args: Mapping[str, Any], by: str) -> Dict[str, Any]:
    act = CardAct("validation_fail", by, {"proof": args["proof"], "agent_id": args.get("agent_id"), "capability": args.get("capability", ""),
                                          "rehold": args.get("rehold")})
    store.update(card_id, actor=CLAUDE, state=rules.OPEN, act=act)
    answer = _answer(store, card_id, act.effects)
    if ((answer["card"] or {}).get("mark") or {}).get("name") != "validation_failed":
        raise CardRefused("not_validating", "that card left review before the verdict landed")
    return answer


def rollup(store: Any, card_id: int, args: Mapping[str, Any], by: str) -> Dict[str, Any]:
    with closing(store._read_connection()) as conn:
        if not flow.rollup_due(conn, card_id):
            return _answer(store, card_id, [])
        kids = conn.execute(f"SELECT {ITEM_COLS} FROM work_items WHERE {reads.CARD_WHERE} AND card_parent = ? ORDER BY id", (card_id,)).fetchall()
    lines = [f"{len(kids)} of {len(kids)} done"]
    for kid in kids:
        card = reads.view(kid, queue=None, children={"total": 0, "done": 0, "in_review": 0})
        lines.append(f"#{kid['id']} {card['title']}: {card['how_to_validate'] or 'no steps written'}" + (f"\nproof: {card['proof']}" if card["proof"] else ""))
    act = CardAct("rollup", by)
    store.update(card_id, actor=CLAUDE, state=rules.REVIEW, review_fields={"review_description": "\n\n".join(lines)[:_MAX_MERGED]}, act=act)
    return _answer(store, card_id, act.effects)


def delete(store: Any, card_id: int, args: Mapping[str, Any], by: str) -> Dict[str, Any]:
    with closing(store._read_connection()) as conn:
        if reads.one(conn, card_id) is None:
            raise CardRefused("not_a_card", "that item is not a card")
        lane_of = conn.execute("SELECT lane FROM work_items WHERE id = ?", (card_id,)).fetchone()
    if by != "owner" and lane.is_task_manager(lane_of):
        raise CardRefused("refused", "the swarm never deletes a task manager task; only the owner does")
    store.delete(card_id, actor=JOE)
    return {"card": None, "effects": [], "data": {}}


OPS = {"finish": finish, "done": done, "send_back": send_back, "reject": reject, "rollup": rollup, "validation_fail": validation_fail,
       "set_column": set_column, "delete": delete}
