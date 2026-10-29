
from __future__ import annotations

import sqlite3
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set

import structlog

from src.cplugs.huddle import actor_log, blockers, groups, lane, lineage, original_ask, rules, review, title as titles, triggers
from src.cplugs.huddle.cards import policy, projection, reads, tx
from src.cplugs.huddle.cards.columns import CARD_COLS, MARKS
from src.cplugs.huddle.rules import CLAUDE, JOE, TaskManagerForbidden
from src.cplugs.huddle.wire import ITEM_COLS
from src.cplugs.sdk.cards import CardRefused

logger = structlog.get_logger()

EVENT_KINDS = frozenset({
    "created", "started", "handoff", "moved", "dealt", "waiting_for_slot", "released", "lapsed", "finished", "accepted",
    "rejected", "sent_back", "done", "paused", "resumed", "swapped", "pinned", "marked", "refresh_asked", "validated",
    "rollup", "deleted", "promoted", "archived", "unarchived", "auto_promote", "noted",
})

_OP_EVENT = {"finish": "finished", "reject": "rejected", "send_back": "sent_back", "done": "done", "rollup": "rollup",
             "validation_fail": "validated"}

_SHAPE_COLS = "list_key, deleted, swarm_ref, kind, state, claude_working, card_holder, card_parent, card_accepted_at, card_queued, created_by, created_key"


@dataclass
class Effect:

    kind: str
    card_id: int
    agent_id: Optional[int] = None
    thread_key: str = ""
    text: str = ""
    category: str = ""
    authority: str = "data"
    ref: str = ""
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CardAct:

    op: str
    by: str
    fields: Mapping[str, Any] = field(default_factory=dict)
    effects: List[Effect] = field(default_factory=list)


@dataclass(frozen=True)
class FlowResult:

    card: Dict[str, Any]
    effects: List[Effect]
    data: Dict[str, Any] = field(default_factory=dict)


def _event(conn: sqlite3.Connection, item_id: int, kind: str, *, list_key: str, by: str, now: float,
           from_col: str = "", to_col: str = "", detail: str = "") -> None:
    if kind not in EVENT_KINDS:
        raise ValueError(f"unknown card event kind {kind!r}")
    conn.execute("INSERT INTO work_card_events (item_id, list_key, at, kind, from_col, to_col, by, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (item_id, list_key, now, kind, from_col, to_col, by, detail))


def _release_holder(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute("UPDATE work_items SET card_last_holder = card_holder, card_holder = NULL, card_held_since = NULL, card_queued = 1 WHERE id = ?", (item_id,))


UNHELD_SQL = "card_holder IS NULL"


def refuse_claim_on_held(row: sqlite3.Row) -> None:
    if projection.card_shaped(row) and row["card_holder"] is not None:
        raise TaskManagerForbidden("card is held by a swarm agent")


def _refuse_claude_on_held(row: sqlite3.Row, by: str) -> None:
    if by == CLAUDE and row["card_holder"] is not None:
        raise TaskManagerForbidden("this card is held by a swarm agent; it moves through the swarm card tools")


def on_state_write(conn: sqlite3.Connection, row: sqlite3.Row, new_state: str, actor: str, now: float,
                   act: Optional[CardAct], *, working: Optional[bool] = None, kind_changed: bool = False,
                   decided: Optional[lineage.Decided] = None) -> None:
    lineage.record_move(conn, row, new_state, actor, now, act, decided)
    triggers.resume_on_move(conn, row, new_state, now)
    blockers.on_move(conn, row, new_state, actor, decided, now)
    if not projection.card_shaped(row):
        return
    if act is None and actor == CLAUDE and row["card_holder"] is not None and (new_state != row["state"] or kind_changed):
        raise TaskManagerForbidden("this card is held by a swarm agent; it moves through the swarm card tools")
    if act is not None:
        _check_act(row, new_state, act)
    keeps_holder = new_state == rules.OPEN
    rehold = act.fields.get("rehold") if act is not None and act.op in ("send_back", "reject", "validation_fail") else None
    holder_after = rehold if rehold is not None else (row["card_holder"] if keeps_holder else None)
    if not keeps_holder:
        queued_after = False
    elif act is not None and act.op == "set_column":
        queued_after = bool(act.fields.get("queued"))
    elif (act is not None and act.op in ("send_back", "reject", "validation_fail")) or row["state"] in _REVIEW_STATES:
        queued_after = True
    else:
        queued_after = bool(row["card_queued"])
    after = {"state": new_state, "card_holder": holder_after,
             "claude_working": bool(row["claude_working"]) and keeps_holder if working is None else working,
             "card_parent": row["card_parent"], "card_accepted_at": None if keeps_holder else row["card_accepted_at"], "card_queued": queued_after}
    if row["card_holder"] is not None and not keeps_holder:
        _release_holder(conn, row["id"])
    cols: Dict[str, Any] = {"card_queued": int(queued_after)}
    if keeps_holder and row["card_accepted_at"] is not None:
        cols["card_accepted_at"] = None
    if rehold is not None:
        cols.update(card_holder=rehold, card_held_since=now, card_started_at=None, card_dealt_to=None, card_beat_at=now)
    if act is not None:
        cols.update(_act_fields(conn, row, new_state, now, act))
    _set(conn, row["id"], cols)
    before_col, after_col = projection.column(row), projection.column(after)
    if before_col == after_col:
        return
    by = act.by if act is not None else actor_log.by_for(actor)
    if act is not None and act.op in _OP_EVENT:
        kind = _OP_EVENT[act.op]
    elif new_state in rules.APPROVED_STATES:
        kind = "done"
    elif before_col == projection.REVIEW and after_col in (projection.TODO, projection.IN_PROGRESS):
        kind = "sent_back"
    else:
        kind = "moved"
    detail = "reply" if kind == "sent_back" and act is None else ("note" if kind == "sent_back" else "")
    if act is not None and act.op == "validation_fail":
        detail = "validation_failed"
    _event(conn, row["id"], kind, list_key=row["list_key"], by=by, now=now, from_col=before_col, to_col=after_col, detail=detail)
    if projection.queued(after):
        policy.request_deal(conn, row["list_key"], "sent_back" if before_col == projection.REVIEW else "reopened", row["id"], now)


_REVIEW_STATES = (rules.REVIEW, rules.WAITING)


def _agent_of(by: str) -> Optional[int]:
    kind, _, raw = by.partition(":")
    return int(raw) if kind == "agent" and raw.isdigit() else None


def _validating_agent(row: sqlite3.Row) -> Optional[int]:
    try:
        record = json.loads(row["card_validation"] or "{}")
    except ValueError:
        return None
    agent = record.get("agent_id")
    return agent if row["card_mark"] == "validating" and record.get("state") == "validating" and isinstance(agent, int) else None


def _check_validating(row: sqlite3.Row, agent_id: Optional[int]) -> None:
    try:
        record = json.loads(row["card_validation"] or "{}")
    except ValueError:
        record = {}
    if row["card_mark"] != "validating" or record.get("state") != "validating" or agent_id is None or record.get("agent_id") != agent_id:
        raise CardRefused("not_validating", "no validation by that agent is waiting on that card")


def _check_pass(row: sqlite3.Row, expect: Mapping[str, Any]) -> None:
    try:
        record = json.loads(row["card_validation"] or "{}")
    except ValueError:
        record = {}
    same_run = all(record.get(key) == expect.get(key) for key in ("agent_id", "started_at", "finished_at"))
    if row["card_mark"] != "validated" or record.get("verdict") != "pass" or not same_run:
        logger.info("swarm_card_auto_done_skipped", card_id=row["id"], reason="the pass no longer covers what is in review")
        raise CardRefused("pass_changed", "the validation pass no longer covers what is in review")


def _check_act(row: sqlite3.Row, new_state: str, act: CardAct) -> None:
    if new_state in rules.APPROVED_STATES and act.by not in ("owner", "auto_done"):
        raise CardRefused("refused", "only the owner moves a card to Done")
    if new_state in rules.APPROVED_STATES and act.by == "auto_done" and lane.is_task_manager(row):
        raise CardRefused(lane.REFUSED_CODE, "the swarm never ticks a task manager task; only the owner does")
    if act.op == "validation_fail":
        _check_validating(row, act.fields.get("agent_id"))
    if act.op == "finish":
        if row["card_holder"] is None or _agent_of(act.by) != row["card_holder"] or row["state"] != rules.OPEN:
            raise CardRefused("not_holder", "you do not hold this card")
    elif act.op in ("done", "send_back", "reject", "validation_fail") and row["state"] not in _REVIEW_STATES:
        raise CardRefused("not_in_review", "that card is not in review")
    elif act.op in ("send_back", "validation_fail") and row["card_accepted_at"] is not None:
        raise CardRefused("not_in_review", "that card was accepted by its parent and reads Done")
    elif act.op == "rollup" and row["state"] != rules.OPEN:
        raise CardRefused("refused", "that card has already left the work")
    if act.op == "done" and act.fields.get("expect_pass") is not None:
        _check_pass(row, act.fields["expect_pass"])


def validation_cols(row: sqlite3.Row, state: str, proof: str, agent_id: Optional[int], now: float, capability: str = "",
                    verdict: str = "") -> Dict[str, Any]:
    try:
        before = {} if state == "validating" else json.loads(row["card_validation"] or "{}")
    except ValueError:
        before = {}
    record = {**before, "state": state, ("started_at" if state == "validating" else "finished_at"): now}
    for key, value in (("agent_id", agent_id), ("capability", capability), ("verdict", verdict)):
        if value not in (None, ""):
            record[key] = value
    cols: Dict[str, Any] = {"card_mark": state, "card_mark_at": now, "card_validation": json.dumps(record)}
    if proof or state == "validating":
        cols["card_proof"] = proof
    return cols


def _act_fields(conn: sqlite3.Connection, row: sqlite3.Row, new_state: str, now: float, act: CardAct) -> Dict[str, Any]:
    cols: Dict[str, Any] = {}
    holder = row["card_holder"]
    if act.op in ("done", "send_back", "reject") and (validator := _validating_agent(row)) is not None:
        act.effects.append(Effect("retire_validator", row["id"], agent_id=validator))
    if act.op == "finish":
        fields = act.fields
        cols.update(card_result=fields.get("result", ""), card_report_id=fields.get("report_id"), card_progress=100, card_mark="",
                    card_mark_at=None, card_dealt_to=None, card_beat_at=now, card_validation="", card_proof="")
        act.effects += [Effect("post", row["id"], agent_id=holder, text="finished", category="result"),
                        Effect("review_entered", row["id"])]
        policy.request_deal(conn, row["list_key"], "agent_freed", row["id"], now)
    elif act.op == "rollup":
        counts = reads.children_counts(conn, [row["id"]])[row["id"]]
        cols.update(card_mark="", card_mark_at=None, card_dealt_to=None)
        act.effects += [Effect("post", row["id"], text="ready_to_validate", category="ready_to_validate",
                               data={"done": counts["done"], "total": counts["total"]}),
                        Effect("review_entered", row["id"])]
    elif act.op == "validation_fail":
        fields = act.fields
        cols.update(validation_cols(row, "validation_failed", fields["proof"], fields.get("agent_id"), now, fields.get("capability", ""), "fail"))
        act.effects.append(Effect("post", row["id"], agent_id=fields.get("agent_id"), text="validation_failed", category="validation_failed"))
        if fields.get("rehold") is not None:
            act.effects.append(Effect("tell", row["id"], agent_id=fields["rehold"], text="validation_failed"))
    elif act.op in ("send_back", "reject"):
        cols.update(card_mark="", card_mark_at=None, card_validation="", card_proof="")
    elif act.op == "done":
        cols.update(card_mark="", card_mark_at=None)
        if act.by == "auto_done":
            act.effects.append(Effect("post", row["id"], text="auto_done", category="auto_done"))
    return cols


def on_inserted(conn: sqlite3.Connection, item_id: int, now: float) -> None:
    row = conn.execute(f"SELECT id, {_SHAPE_COLS} FROM work_items WHERE id = ?", (item_id,)).fetchone()
    if row is None or not projection.card_shaped(row):
        return
    by = "owner" if row["created_by"] == JOE else (row["created_key"] or "claude")
    _event(conn, item_id, "created", list_key=row["list_key"], by=by, now=now, to_col=projection.column(row))
    policy.request_deal(conn, row["list_key"], "card_created", item_id, now)


def on_tombstone(conn: sqlite3.Connection, rows: Sequence[sqlite3.Row], now: float, by: str = "owner") -> None:
    for row in rows:
        if not projection.card_shaped(row):
            continue
        _refuse_claude_on_held(row, by)
        if row["card_holder"] is not None:
            _release_holder(conn, row["id"])
        _event(conn, row["id"], "deleted", list_key=row["list_key"], by=by, now=now, from_col=projection.column(row))


def on_list_move(conn: sqlite3.Connection, row: sqlite3.Row, new_list_key: str, now: float, by: str = "owner") -> None:
    if not projection.card_shaped(row):
        return
    _refuse_claude_on_held(row, by)
    before_col = projection.column(row)
    conn.execute("UPDATE work_items SET card_last_holder = CASE WHEN card_holder IS NOT NULL THEN card_holder ELSE card_last_holder END, "
                 "card_holder = NULL, card_held_since = NULL, card_pin_agent = NULL, card_dealt_to = NULL, card_queued = 0, "
                 "card_mark = CASE WHEN card_mark = 'waiting_for_slot' THEN '' ELSE card_mark END WHERE id = ?", (row["id"],))
    after_col = projection.column({**{k: row[k] for k in ("state", "claude_working", "card_parent", "card_accepted_at")}, "card_holder": None, "card_queued": 0})
    _event(conn, row["id"], "moved", list_key=new_list_key, by=by, now=now, from_col=before_col, to_col=after_col,
           detail=f"list {row['list_key']} to {new_list_key}")
    if after_col == projection.TODO:
        policy.request_deal(conn, new_list_key, "list_moved", row["id"], now)



_WRITABLE = frozenset(c.strip() for c in CARD_COLS.split(",")) - {"claude_working_by", "phone_sent_at"}
_WRITABLE = _WRITABLE | {"lane"}
MAX_HANDOFF_CHARS = 8000
MAX_SUMMARY_CHARS = 200
MAX_OWNER_NOTE_CHARS = 4000
MAX_RESULT_CHARS = 4000


def _set(conn: sqlite3.Connection, item_id: int, cols: Mapping[str, Any]) -> None:
    unknown = set(cols) - _WRITABLE
    if unknown:
        raise ValueError(f"not a writable card column: {sorted(unknown)[0]}")
    if cols:
        conn.execute("UPDATE work_items SET " + ", ".join(f"{name} = ?" for name in cols) + " WHERE id = ?", [*cols.values(), item_id])


def _row(conn: sqlite3.Connection, card_id: int) -> sqlite3.Row:
    row = conn.execute(f"SELECT {ITEM_COLS} FROM work_items WHERE id = ? AND deleted = 0", (card_id,)).fetchone()
    if row is None or not projection.card_shaped(row):
        raise CardRefused("not_a_card", "that item is not a card")
    return row


def _done(conn: sqlite3.Connection, card_id: int, effects: List[Effect], data: Optional[Dict[str, Any]] = None) -> FlowResult:
    return FlowResult(card=reads.one(conn, card_id) or {}, effects=effects, data=data or {})


def _touch(conn: sqlite3.Connection, card_id: int, by: str, now: float, *, mark: Optional[bool] = None) -> None:
    owner = by in ("owner", "auto_done")
    tx.bump(conn, card_id, JOE if owner else CLAUDE, now, mark=owner if mark is None else mark)


def _need_holder(row: sqlite3.Row, agent_id: int) -> None:
    if row["card_holder"] != agent_id or row["state"] != rules.OPEN:
        raise CardRefused("not_holder", "you do not hold this card")


def _take(conn: sqlite3.Connection, row: sqlite3.Row, agent_id: int, by: str, now: float, effects: List[Effect]) -> None:
    place = reads.one(conn, row["id"])["queue_index"]
    handed = row["card_mark"] == "handing_off" and row["card_last_holder"] not in (None, agent_id)
    _set(conn, row["id"], {"card_holder": agent_id, "card_held_since": now, "card_started_at": None, "card_dealt_to": None,
                           "card_mark": "", "card_mark_at": None, "card_beat_at": now, "card_queued": 1, "card_owner_note": ""})
    _event(conn, row["id"], "dealt", list_key=row["list_key"], by=by, now=now, from_col=projection.column(row), to_col=projection.IN_PROGRESS,
           detail=f"to agent {agent_id}")
    effects.append(Effect("tell", row["id"], agent_id=agent_id, text="dealt", data={"note": row["card_owner_note"]}))
    if handed:
        effects.append(Effect("post", row["id"], agent_id=agent_id, text="handed_off", category="handed_off", data={"old": row["card_last_holder"], "lapsed": True}))
    else:
        effects.append(Effect("post", row["id"], agent_id=agent_id, text="dealt", category="dealt", data={"dealer": _agent_of(by), "place": place}))


def create(conn: sqlite3.Connection, *, list_key: str, title: str, text: str, by: str, origin: str, parent: Optional[int],
           how_to_validate: str, before_id: Optional[int], now: float, summary: str = "", queued: bool = False) -> FlowResult:
    from src.cplugs.huddle.store import TaskManagerStore

    parent_row = _row(conn, parent) if parent is not None else None
    actor = JOE if by == "owner" else CLAUDE
    reviewing = {**review.clean_fields({"review_description": how_to_validate or None}), **titles.clean_fields(title)}
    seq = TaskManagerStore._next_seq(conn)
    item_id = TaskManagerStore._insert_item(conn, list_key, rules.clean_text(text or title, "text", rules.MAX_TEXT), actor=actor, seq=seq, now=now,
                                       created_key=rules.OWNER_KEY if actor == JOE else by, reviewing=reviewing)
    _set(conn, item_id, {"card_origin": origin, "lane": lane.for_new(list_key=list_key, card_origin=origin), "card_parent": parent, "card_summary": rules.clean_text(summary, "summary", MAX_SUMMARY_CHARS, allow_blank=True),
                         "card_queued": int(queued)})
    if parent_row is not None:
        original_ask.copy_link(conn, item_id, parent_row["inbox_id"])
    if before_id is not None:
        card = _row(conn, item_id)
        full = {r["id"]: r for r in conn.execute(f"SELECT {ITEM_COLS} FROM work_items WHERE list_key = ? AND deleted = 0", (list_key,))}
        pinned = [i for i, r in full.items() if r["card_pin_place"] and projection.column(r) == projection.TODO]
        places_before = projection.queue_index([full[r["id"]] for r in groups._ordered(conn, list_key)])
        order = _place(conn, card, before_id, now)
        if actor == CLAUDE and pinned:
            places_after = projection.queue_index([full[i] for i in order])
            if any(places_after.get(i) != places_before.get(i) for i in pinned):
                raise CardRefused("pinned", "a card the owner pinned would change place")
    return _done(conn, item_id, [])


def _place(conn: sqlite3.Connection, row: sqlite3.Row, before_id: Optional[int], now: float) -> List[int]:
    from src.cplugs.huddle.store import TaskManagerStore

    key = row["list_key"]
    rows = groups._ordered(conn, key)
    before = None if before_id is None else next((r for r in rows if r["id"] == before_id and r["id"] != row["id"]), None)
    if before_id is not None and before is None:
        raise CardRefused("stale", "that card is no longer in this queue")
    group = row["group_id"] if before is None else before["group_id"]
    index = None if before is None else [r["id"] for r in rows if r["group_id"] == group and r["id"] != row["id"]].index(before_id)
    order = groups.place_in_section(rows, row["id"], group, [g["id"] for g in groups.live_groups(conn, key)], index)
    if order != [r["id"] for r in rows] or group != row["group_id"]:
        seq = TaskManagerStore._next_seq(conn)
        groups.renumber(conn, order, {r["id"]: r["position"] for r in rows}, seq, now)
        conn.execute("UPDATE work_items SET group_id = ?, seq = ?, updated_at = ?, revision = revision + 1 WHERE id = ?", (group, seq, now, row["id"]))
    return order


def start(conn: sqlite3.Connection, card_id: int, *, agent_id: int, now: float) -> FlowResult:
    row = _row(conn, card_id)
    if row["card_paused_mode"]:
        raise CardRefused("paused", "this card is paused; wait for the owner to resume it")
    if row["card_holder"] == agent_id and row["state"] == rules.OPEN:
        cols: Dict[str, Any] = {"card_beat_at": now}
        if row["card_mark"] == "stalled":
            cols.update(card_mark="", card_mark_at=None)
        if row["card_started_at"] is None:
            cols["card_started_at"] = now
            _event(conn, card_id, "started", list_key=row["list_key"], by=f"agent:{agent_id}", now=now)
        _set(conn, card_id, cols)
        _touch(conn, card_id, f"agent:{agent_id}", now, mark=False)
        return _done(conn, card_id, [])
    if row["card_dealt_to"] != agent_id or row["card_holder"] is not None or row["state"] != rules.OPEN:
        raise CardRefused("not_holder", "this card was not dealt to you")
    if row["claude_working"]:
        raise CardRefused("held", "a session already claimed this card")
    _set(conn, card_id, {"card_holder": agent_id, "card_held_since": now, "card_started_at": now, "card_dealt_to": None,
                         "card_mark": "", "card_mark_at": None, "card_beat_at": now})
    _event(conn, card_id, "started", list_key=row["list_key"], by=f"agent:{agent_id}", now=now, from_col=projection.TODO, to_col=projection.IN_PROGRESS)
    _touch(conn, card_id, f"agent:{agent_id}", now, mark=False)
    return _done(conn, card_id, [])


def handoff(conn: sqlite3.Connection, card_id: int, *, agent_id: int, handoff: Optional[str], progress: Optional[int], now: float) -> FlowResult:
    row = _row(conn, card_id)
    _need_holder(row, agent_id)
    if handoff is not None and len(handoff) > MAX_HANDOFF_CHARS:
        raise CardRefused("too_long", f"the handoff must be at most {MAX_HANDOFF_CHARS} characters")
    if progress is not None and (type(progress) is not int or not 0 <= progress <= 100):
        raise CardRefused("bad_progress", "progress is a whole number from 0 to 100")
    cols: Dict[str, Any] = {"card_beat_at": now}
    if handoff is not None:
        cols["card_handoff"] = handoff
    if progress is not None:
        cols["card_progress"] = progress
    stalled = row["card_mark"] == "stalled"
    if stalled:
        cols.update(card_mark="", card_mark_at=None)
    _set(conn, card_id, cols)
    changed = handoff is not None or progress is not None or stalled
    if changed:
        _touch(conn, card_id, f"agent:{agent_id}", now, mark=False)
    if handoff is not None:
        _event(conn, card_id, "handoff", list_key=row["list_key"], by=f"agent:{agent_id}", now=now)
    return _done(conn, card_id, [], {"changed": changed})


def release(conn: sqlite3.Connection, card_id: int, *, by: str, reason: str, now: float) -> FlowResult:
    row = _row(conn, card_id)
    holder, nxt = row["card_holder"], row["card_dealt_to"]
    if holder is None or row["state"] != rules.OPEN:
        raise CardRefused("not_held", "nobody holds this card")
    if _agent_of(by) is not None and _agent_of(by) != holder:
        raise CardRefused("not_holder", "you do not hold this card")
    effects: List[Effect] = []
    _release_holder(conn, card_id)
    note = reason[:500]
    if nxt is not None:
        _set(conn, card_id, {"card_holder": nxt, "card_held_since": now, "card_started_at": None, "card_dealt_to": None,
                             "card_mark": "", "card_mark_at": None, "card_beat_at": now})
        effects += [Effect("tell", card_id, agent_id=nxt, text="dealt"),
                    Effect("post", card_id, agent_id=nxt, text="handed_off", category="handed_off", data={"old": holder, "lapsed": False})]
        _event(conn, card_id, "released", list_key=row["list_key"], by=by, now=now, from_col=projection.IN_PROGRESS,
               to_col=projection.IN_PROGRESS, detail=f"{note} (handed to agent {nxt})")
    else:
        _set(conn, card_id, {"card_started_at": None, "card_mark": "", "card_mark_at": None})
        _event(conn, card_id, "released", list_key=row["list_key"], by=by, now=now, from_col=projection.IN_PROGRESS,
               to_col=projection.IN_PROGRESS, detail=note)
        policy.request_deal(conn, row["list_key"], "released", card_id, now)
        if by == "owner":
            effects.append(Effect("tell", card_id, agent_id=holder, text="owner_release"))
    _touch(conn, card_id, by, now)
    return _done(conn, card_id, effects)


def deal(conn: sqlite3.Connection, card_id: int, *, agent_id: int, by: str, slot_ok: bool, now: float, commit: bool = False) -> FlowResult:
    row = _row(conn, card_id)
    if row["card_holder"] is not None or row["claude_working"]:
        raise CardRefused("held", "this card is already held")
    if row["card_paused_mode"]:
        raise CardRefused("paused", "this card is paused")
    if row["card_dealt_to"] is not None:
        raise CardRefused("dealt", f"this card was already dealt to agent {row['card_dealt_to']}")
    if row["card_pin_agent"] not in (None, agent_id):
        raise CardRefused("pinned_elsewhere", f"this card is pinned to agent {row['card_pin_agent']}")
    if not (projection.dealable(row) or (commit and projection.column(row) == projection.TODO and projection.dealable({**dict(row), "card_queued": 1}))):
        raise CardRefused("not_dealable", "this card is not queued in progress (a todo card is moved to in progress first)")
    effects: List[Effect] = []
    if slot_ok:
        _take(conn, row, agent_id, by, now, effects)
    else:
        _set(conn, card_id, {"card_dealt_to": agent_id, "card_mark": "waiting_for_slot", "card_mark_at": now})
        _event(conn, card_id, "waiting_for_slot", list_key=row["list_key"], by=by, now=now, detail=f"for agent {agent_id}")
        effects.append(Effect("post", card_id, agent_id=agent_id, text="waiting_for_slot", category="waiting_for_slot"))
    _touch(conn, card_id, by, now, mark=False)
    return _done(conn, card_id, effects)


def complete_slot(conn: sqlite3.Connection, card_id: int, *, now: float) -> FlowResult:
    row = _row(conn, card_id)
    if (row["card_mark"] != "waiting_for_slot" or row["card_dealt_to"] is None or row["card_holder"] is not None
            or row["card_paused_mode"] or row["state"] != rules.OPEN):
        raise CardRefused("not_waiting", "this card is not waiting for a slot")
    effects: List[Effect] = []
    _take(conn, row, row["card_dealt_to"], "server", now, effects)
    _touch(conn, card_id, "server", now, mark=False)
    return _done(conn, card_id, effects)


def swap(conn: sqlite3.Connection, card_id: int, *, agent_id: int, by: str, now: float) -> FlowResult:
    row = _row(conn, card_id)
    if row["card_holder"] is None or row["state"] != rules.OPEN:
        raise CardRefused("not_held", "only a held card can be swapped")
    if row["card_holder"] == agent_id:
        raise CardRefused("same_agent", "that agent already holds this card")
    if row["card_pin_agent"] not in (None, agent_id):
        raise CardRefused("pinned_elsewhere", f"this card is pinned to agent {row['card_pin_agent']}")
    _set(conn, card_id, {"card_dealt_to": agent_id, "card_mark": "handing_off", "card_mark_at": now})
    _event(conn, card_id, "swapped", list_key=row["list_key"], by=by, now=now, detail=f"agent {row['card_holder']} to agent {agent_id}")
    _touch(conn, card_id, by, now, mark=False)
    return _done(conn, card_id, [Effect("tell", card_id, agent_id=row["card_holder"], text="swap", data={"to": agent_id})])


def pin(conn: sqlite3.Connection, card_id: int, *, agent_id: Optional[int], place: bool, by: str, now: float) -> FlowResult:
    row = _row(conn, card_id)
    _set(conn, card_id, {"card_pin_agent": agent_id, "card_pin_place": int(place)})
    _event(conn, card_id, "pinned", list_key=row["list_key"], by=by, now=now, detail=f"agent {agent_id}, place {int(place)}")
    _touch(conn, card_id, by, now, mark=False)
    return _done(conn, card_id, [])


def mark(conn: sqlite3.Connection, card_id: int, *, mark: str, by: str, detail: str, now: float) -> FlowResult:
    if mark and mark not in MARKS:
        raise CardRefused("bad_mark", f"unknown mark {mark}")
    row = _row(conn, card_id)
    _set(conn, card_id, {"card_mark": mark, "card_mark_at": now if mark else None})
    _event(conn, card_id, "marked", list_key=row["list_key"], by=by, now=now, detail=f"{mark or 'cleared'} {detail}".strip())
    _touch(conn, card_id, by, now, mark=False)
    return _done(conn, card_id, [])


def move(conn: sqlite3.Connection, card_id: int, *, before_id: Optional[int], by: str, reason: str, now: float, pin_place: bool = False) -> FlowResult:
    row = _row(conn, card_id)
    lane = projection.waiting_lane(row)
    if lane is None:
        raise CardRefused("not_todo", "only a waiting card (todo, or queued in progress) moves in the queue")
    agent = _agent_of(by)
    full = {r["id"]: r for r in conn.execute(f"SELECT {ITEM_COLS} FROM work_items WHERE list_key = ? AND deleted = 0", (row["list_key"],))}
    if before_id is not None and (before_id not in full or projection.waiting_lane(full[before_id]) != lane):
        raise CardRefused("stale", "that card is no longer waiting in this lane")
    if agent is not None and row["card_pin_place"]:
        raise CardRefused("pinned", "the owner pinned this card's place")
    pinned = [i for i, r in full.items() if r["card_pin_place"] and projection.waiting_lane(r) is not None]
    places_before = projection.queue_index([full[r["id"]] for r in groups._ordered(conn, row["list_key"])])
    order = _place(conn, row, before_id, now)
    if agent is not None and pinned:
        places_after = projection.queue_index([full[i] for i in order])
        if any(places_after.get(i) != places_before.get(i) for i in pinned):
            raise CardRefused("pinned", "a card the owner pinned would change place")
    if pin_place:
        _set(conn, card_id, {"card_pin_place": 1})
    where = f"above #{before_id}" if before_id is not None else "to the bottom"
    _event(conn, card_id, "moved", list_key=row["list_key"], by=by, now=now, from_col=lane, to_col=lane, detail=f"{where}: {reason}"[:500])
    _touch(conn, card_id, by, now, mark=False)
    effects = [Effect("post", card_id, agent_id=agent, text="reordered", category="reordered",
                      data={"other": before_id, "reason": reason})] if agent is not None else []
    return _done(conn, card_id, effects)


def suggest(conn: sqlite3.Connection, card_id: int, *, before_id: Optional[int], agent_id: int, reason: str, now: float) -> FlowResult:
    row = _row(conn, card_id)
    if projection.waiting_lane(row) is None:
        raise CardRefused("not_todo", "only a waiting card (todo, or queued in progress) is reordered")
    if before_id is not None:
        other = conn.execute(f"SELECT {ITEM_COLS} FROM work_items WHERE id = ? AND list_key = ? AND deleted = 0", (before_id, row["list_key"])).fetchone()
        if other is None or projection.waiting_lane(other) != projection.waiting_lane(row):
            raise CardRefused("stale", "that card is no longer waiting in this queue")
    suggestion = policy.add_suggestion(conn, list_key=row["list_key"], card_id=card_id, before_id=before_id, agent_id=agent_id, reason=reason, now=now)
    effect = Effect("post", card_id, agent_id=agent_id, text="reorder_suggested", category="reorder_suggested",
                    data={"other": before_id, "reason": reason, "suggestion_id": suggestion})
    return _done(conn, card_id, [effect], {"suggestion_id": suggestion, "changed": False})


def _descendants(conn: sqlite3.Connection, root: int) -> List[sqlite3.Row]:
    found: List[sqlite3.Row] = []
    seen: Set[int] = {root}
    frontier = [root]
    while frontier:
        marks = ",".join("?" * len(frontier))
        rows = [r for r in conn.execute(f"SELECT {ITEM_COLS} FROM work_items WHERE card_parent IN ({marks}) AND deleted = 0", frontier) if r["id"] not in seen]
        frontier = [r["id"] for r in rows]
        seen.update(frontier)
        found += [r for r in rows if projection.card_shaped(r)]
    return found


def pause(conn: sqlite3.Connection, card_id: int, *, mode: str, by: str, now: float) -> FlowResult:
    if mode not in ("after_step", "now"):
        raise CardRefused("bad_mode", "pause is after_step or now")
    root = _row(conn, card_id)
    if projection.column(root) == projection.DONE:
        raise CardRefused("done", "a done card cannot be paused")
    children = [r for r in _descendants(conn, card_id) if projection.column(r) != projection.DONE and not r["card_paused_mode"]]
    effects: List[Effect] = []
    agents: List[int] = []
    for row in [root, *children]:
        _set(conn, row["id"], {"card_paused_mode": mode, "card_paused_by": card_id, "card_paused_at": now})
        _event(conn, row["id"], "paused", list_key=row["list_key"], by=by, now=now, detail=mode if row["id"] == card_id else f"{mode}, with #{card_id}")
        _touch(conn, row["id"], by, now, mark=False)
        holder = row["card_holder"]
        if holder is not None:
            agents.append(holder)
            if mode == "now":
                effects.append(Effect("interrupt", row["id"], agent_id=holder))
            effects.append(Effect("tell", row["id"], agent_id=holder, text="pause_now" if mode == "now" else "pause_after_step"))
    effects.append(Effect("post", card_id, text="paused", category="paused", data={"children": len(children), "agents": agents}))
    return _done(conn, card_id, effects, {"cascaded": [r["id"] for r in children], "agents": agents, "list_keys": sorted({r["list_key"] for r in children})})


def resume(conn: sqlite3.Connection, card_id: int, *, by: str, now: float) -> FlowResult:
    root = _row(conn, card_id)
    if not root["card_paused_mode"]:
        raise CardRefused("not_paused", "this card is not paused")
    if root["card_paused_by"] not in (None, card_id):
        raise CardRefused("paused_with_parent", f"this card is paused with #{root['card_paused_by']}; resume that one")
    rows = [root] + conn.execute(f"SELECT {ITEM_COLS} FROM work_items WHERE card_paused_by = ? AND id != ? AND deleted = 0", (card_id, card_id)).fetchall()
    effects: List[Effect] = []
    agents: List[int] = []
    asked: Set[str] = set()
    for row in rows:
        _set(conn, row["id"], {"card_paused_mode": "", "card_paused_by": None, "card_paused_at": None,
                               **({"card_beat_at": now} if row["card_holder"] is not None else {})})
        _event(conn, row["id"], "resumed", list_key=row["list_key"], by=by, now=now)
        _touch(conn, row["id"], by, now, mark=False)
        if row["card_holder"] is not None:
            agents.append(row["card_holder"])
            effects.append(Effect("tell", row["id"], agent_id=row["card_holder"], text="resume"))
        elif projection.queued(row) and row["list_key"] not in asked:
            asked.add(row["list_key"])
            policy.request_deal(conn, row["list_key"], "resumed", row["id"], now)
    effects.append(Effect("post", card_id, text="resumed", category="resumed", data={"children": len(rows) - 1, "agents": agents}))
    return _done(conn, card_id, effects, {"cascaded": [r["id"] for r in rows[1:]], "agents": agents, "list_keys": sorted({r["list_key"] for r in rows[1:]})})


def lapse(conn: sqlite3.Connection, card_id: int, *, reason: str, now: float, seen: Optional[Sequence[Optional[float]]] = None) -> FlowResult:
    row = _row(conn, card_id)
    holder = row["card_holder"]
    if holder is None or row["state"] != rules.OPEN:
        raise CardRefused("not_held", "nobody holds this card")
    if seen is not None and (row["card_beat_at"], row["card_held_since"]) != tuple(seen):
        raise CardRefused("stale", "the card's beat moved since the sweep read it")
    if policy.dealing_on(conn, row["list_key"]):
        _release_holder(conn, card_id)
        _set(conn, card_id, {"card_mark": "handing_off", "card_mark_at": now, "card_started_at": None, "card_dealt_to": None})
        _event(conn, card_id, "lapsed", list_key=row["list_key"], by="server", now=now, from_col=projection.IN_PROGRESS, to_col=projection.IN_PROGRESS, detail=reason[:500])
        policy.request_deal(conn, row["list_key"], "lease_lapsed", card_id, now)
        effects = [Effect("tell", card_id, agent_id=holder, text="lapse_stop"),
                   Effect("post", card_id, agent_id=holder, text="lapsed", category="important", data={"reason": reason[:200]})]
    else:
        if row["card_mark"] == "stalled":
            return _done(conn, card_id, [], {"changed": False})
        _set(conn, card_id, {"card_mark": "stalled", "card_mark_at": now})
        _event(conn, card_id, "lapsed", list_key=row["list_key"], by="server", now=now, detail=reason[:500])
        effects = [Effect("post", card_id, agent_id=holder, text="stalled", category="important")]
    _touch(conn, card_id, "server", now, mark=True)
    return _done(conn, card_id, effects)


def rollup_due(conn: sqlite3.Connection, parent_id: int) -> bool:
    row = conn.execute(f"SELECT {ITEM_COLS} FROM work_items WHERE id = ? AND deleted = 0", (parent_id,)).fetchone()
    if row is None or not projection.card_shaped(row) or row["state"] != rules.OPEN:
        return False
    counts = reads.children_counts(conn, [parent_id])[parent_id]
    return counts["total"] > 0 and counts["done"] == counts["total"]


def accept_child(conn: sqlite3.Connection, card_id: int, *, by_agent: int, report_id: int, now: float) -> FlowResult:
    row = _row(conn, card_id)
    if row["card_parent"] is None:
        raise CardRefused("not_a_child", "this card has no parent card")
    if row["state"] not in _REVIEW_STATES:
        raise CardRefused("not_in_review", "that card is not in review")
    if row["card_accepted_at"] is None:
        _set(conn, card_id, {"card_accepted_at": now, "card_report_id": report_id})
        _event(conn, card_id, "accepted", list_key=row["list_key"], by=f"agent:{by_agent}", now=now, from_col=projection.REVIEW, to_col=projection.DONE)
        _touch(conn, card_id, f"agent:{by_agent}", now, mark=False)
        policy.request_deal(conn, row["list_key"], "agent_freed", card_id, now)
    effects = [Effect("rollup", row["card_parent"])] if rollup_due(conn, row["card_parent"]) else []
    return _done(conn, card_id, effects)


def asked_refresh(conn: sqlite3.Connection, card_id: int, *, now: float) -> FlowResult:
    row = _row(conn, card_id)
    if row["card_holder"] is None:
        raise CardRefused("not_held", "nobody holds this card")
    _set(conn, card_id, {"card_refresh_asked_at": now})
    _event(conn, card_id, "refresh_asked", list_key=row["list_key"], by="server", now=now)
    return _done(conn, card_id, [Effect("tell", card_id, agent_id=row["card_holder"], text="refresh")], {"changed": False})


def validation(conn: sqlite3.Connection, card_id: int, *, state: str, proof: str, agent_id: Optional[int], now: float,
               capability: str = "", verdict: str = "", replaces: Optional[int] = None) -> FlowResult:
    if state not in ("validating", "validated"):
        raise CardRefused("bad_mark", f"unknown validation state {state}")
    row = _row(conn, card_id)
    if row["state"] not in _REVIEW_STATES or row["card_accepted_at"] is not None:
        raise CardRefused("not_in_review", "that card is not in review")
    if state == "validated":
        _check_validating(row, agent_id)
    elif (current := _validating_agent(row)) is not None and current != replaces:
        raise CardRefused("already_validating", "that card is already being validated")
    _set(conn, card_id, validation_cols(row, state, proof, agent_id, now, capability, verdict))
    _event(conn, card_id, "validated", list_key=row["list_key"], by=f"agent:{agent_id}" if agent_id else "server", now=now, detail=state)
    _touch(conn, card_id, "server", now, mark=True)
    post = [Effect("post", card_id, agent_id=agent_id, text="validated", category="validated", data={"capability": capability})] if state == "validated" else []
    return _done(conn, card_id, post)




def _unhold(conn: sqlite3.Connection, row: sqlite3.Row) -> None:
    if row["card_holder"] is not None:
        _release_holder(conn, row["id"])
    mark = {"card_mark": "", "card_mark_at": None} if row["card_mark"] in ("waiting_for_slot", "handing_off") else {}
    _set(conn, row["id"], {"card_queued": 0, "card_dealt_to": None, "card_started_at": None, **mark})


def set_lane(conn: sqlite3.Connection, card_id: int, *, queued: bool, by: str, now: float) -> FlowResult:
    row = _row(conn, card_id)
    if row["state"] != rules.OPEN:
        raise CardRefused("not_open", "that card is not open")
    before = projection.column(row)
    target = projection.IN_PROGRESS if queued else projection.TODO
    if before == target:
        return _done(conn, card_id, [], {"changed": False})
    if row["claude_working"]:
        raise CardRefused("claimed", "a session is working on this card outside the swarm")
    if queued:
        _set(conn, card_id, {"card_queued": 1})
        policy.request_deal(conn, row["list_key"], "queued", card_id, now)
    else:
        _unhold(conn, row)
    _event(conn, card_id, "moved", list_key=row["list_key"], by=by, now=now, from_col=before, to_col=target,
           detail="queued by the owner" if queued else "paused by the owner")
    _touch(conn, card_id, by, now)
    return _done(conn, card_id, [])


def archive(conn: sqlite3.Connection, card_id: int, *, on: bool, by: str, now: float) -> FlowResult:
    row = _row(conn, card_id)
    if (row["card_archived_at"] is not None) == on:
        return _done(conn, card_id, [], {"changed": False})
    before = projection.column(row)
    if on and row["state"] == rules.OPEN and before == projection.IN_PROGRESS and not row["claude_working"]:
        _unhold(conn, row)
    _set(conn, card_id, {"card_archived_at": now if on else None})
    _event(conn, card_id, "archived" if on else "unarchived", list_key=row["list_key"], by=by, now=now, from_col=before,
           to_col=projection.column(_row(conn, card_id)))
    _touch(conn, card_id, by, now)
    return _done(conn, card_id, [])


def set_auto_promote(conn: sqlite3.Connection, card_id: int, *, on: bool, by: str, now: float) -> FlowResult:
    row = _row(conn, card_id)
    if on and projection.column(row) != projection.TODO:
        raise CardRefused("not_todo", "only a todo card is flagged for auto-promote")
    if bool(row["card_auto_promote"]) == on:
        return _done(conn, card_id, [], {"changed": False})
    _set(conn, card_id, {"card_auto_promote": int(on)})
    _event(conn, card_id, "auto_promote", list_key=row["list_key"], by=by, now=now, detail="on" if on else "off")
    if on:
        policy.request_deal(conn, row["list_key"], "auto_promote", card_id, now)
    _touch(conn, card_id, by, now)
    return _done(conn, card_id, [])


def promote(conn: sqlite3.Connection, card_id: int, *, by: str, now: float) -> FlowResult:
    row = _row(conn, card_id)
    if not (projection.column(row) == projection.TODO and row["card_auto_promote"] and row["state"] == rules.OPEN
            and row["card_paused_mode"] == "" and row["card_archived_at"] is None):
        raise CardRefused("not_promotable", "that card is no longer a flagged todo card")
    _set(conn, card_id, {"card_queued": 1, "card_auto_promote": 0})
    _event(conn, card_id, "promoted", list_key=row["list_key"], by=by, now=now, from_col=projection.TODO, to_col=projection.IN_PROGRESS,
           detail="auto-promote: nothing else was queued")
    _touch(conn, card_id, by, now, mark=False)
    return _done(conn, card_id, [])


def owner_note(conn: sqlite3.Connection, card_id: int, *, note: str, by: str, now: float) -> FlowResult:
    row = _row(conn, card_id)
    text = rules.clean_text(note, "note", MAX_OWNER_NOTE_CHARS, allow_blank=True)
    if text == row["card_owner_note"]:
        return _done(conn, card_id, [], {"changed": False})
    _set(conn, card_id, {"card_owner_note": text})
    _event(conn, card_id, "noted", list_key=row["list_key"], by=by, now=now, detail=text[:500])
    _touch(conn, card_id, by, now)
    return _done(conn, card_id, [])
