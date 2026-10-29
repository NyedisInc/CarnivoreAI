
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Mapping, Optional, Sequence

import structlog

from src.core.swarm import body, guard, memory, owner_message, reports, store
from src.core.swarm.cards import capacity, dealer, deliver, effects, fit, notices, permits, port as card_port, texts
from src.cplugs.sdk.cards import CardRefused

logger = structlog.get_logger()

MAX_FINISH_CHARS = 4000
MAX_ASK_CHARS = 500
_CLOSE_SKIPS = ("task_manager_lane", "not_in_review")
MAX_TITLE_CHARS = 120
MAX_SUMMARY_CHARS = 200
COLUMNS = ("todo", "in_progress", "review", "done")
_VALIDATION_TASK_TYPE = "card-validation"
MAX_CARD_TEXT = 2000


def agent_id_of(by: str) -> Optional[int]:
    return int(by.split(":", 1)[1]) if by.startswith("agent:") else None


async def _agent(by: str) -> Optional[Dict[str, Any]]:
    agent_id = agent_id_of(by)
    if agent_id is None:
        return None
    row = await body.run_db(lambda c: store.get_agent(c, agent_id))
    if row is None or row["torn_down_at"] is not None:
        raise CardRefused("not_a_swarm_agent", "swarm tools are for Swarm agents")
    return row


async def _card(card_id: int) -> Dict[str, Any]:
    card = await card_port.get().card(int(card_id))
    if card is None:
        raise CardRefused("not_a_card", f"no card #{card_id}")
    return card


async def _company_of(project_id: Optional[int]) -> Optional[int]:
    if project_id is None:
        return None
    row = await body.run_db(lambda c: c.execute("SELECT company_id FROM projects WHERE id = ?", (project_id,)).fetchone())
    return row["company_id"] if row else None


def _no_secrets(where: str, *texts: Optional[str]) -> None:
    for text in texts:
        try:
            memory.refuse_secrets(text or "", where)
        except memory.SwarmFileError as exc:
            raise CardRefused("secret", str(exc)) from None


async def _allow(by: str, op: str, card: Optional[Mapping[str, Any]], args: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    agent = await _agent(by)
    if agent is not None:
        refusal = permits.check(agent, op, card, args, company_id=await _company_of(card.get("project_id")) if card else None)
        if refusal:
            raise CardRefused("not_allowed", refusal)
    return agent


async def _act(app_state: Any, op: str, card_id: Optional[int], args: Mapping[str, Any], by: str, *,
               skip: Sequence[str] = ()) -> Dict[str, Any]:
    result = await card_port.get().act(op, card_id, args, by)
    await effects.run(app_state, [e for e in result["effects"] if e["kind"] not in skip])
    return result


async def create(app_state: Any, card_id: Optional[int], args: Mapping[str, Any], *, by: str, origin: Optional[str] = None) -> Dict[str, Any]:
    agent = await _agent(by)
    title = (args.get("title") or "").strip()
    if not title or len(title) > MAX_TITLE_CHARS:
        raise CardRefused("bad_card", f"title is required, at most {MAX_TITLE_CHARS} characters")
    summary = " ".join((args.get("summary") or "").split())
    if len(summary) > MAX_SUMMARY_CHARS:
        raise CardRefused("bad_card", f"summary is at most {MAX_SUMMARY_CHARS} characters")
    _no_secrets("card", title, summary, args.get("text"), args.get("how_to_validate"))
    parent = await _card(args["parent"]) if args.get("parent") is not None else None
    list_key = args.get("list_key") or (str(args["project_id"]) if args.get("project_id") is not None else None)
    list_key = list_key or (str(parent["list_key"]) if parent else (agent["thread_key"] if agent and agent["rank"] in ("project", "company") else None))
    if not list_key:
        raise CardRefused("bad_card", "name the project (project_id) the card belongs to")
    if agent is not None:
        project = int(list_key) if str(list_key).isdigit() else None
        refusal = permits.can_create(agent, str(list_key), parent, company_id=await _company_of(project),
                                     parent_company_id=await _company_of(parent.get("project_id")) if parent else None)
        if refusal:
            raise CardRefused("not_allowed", refusal)
        own_list = agent["rank"] == "project" and str(agent["thread_key"]) == str(list_key)
        in_work = parent is not None and parent["column"] == "in_progress"
        if args.get("queued") and origin is None and not (own_list or in_work):
            raise CardRefused("not_allowed", "only the project agent makes a card queued, and only in its own project")
        origin = origin or ("owner_message:turn" if guard.turn_authority(agent["id"]) == guard.OWNER else f"agent:{agent['id']}")
    sent = {"list_key": str(list_key), "title": title, "text": args.get("text", ""), "parent": args.get("parent"),
            "how_to_validate": args.get("how_to_validate", ""), "before_id": args.get("before_id"), "origin": origin or "owner",
            "summary": summary, "queued": bool(args.get("queued")) or (parent is not None and parent["column"] == "in_progress")}
    result = await card_port.get().act("create", None, sent, by)
    line = {"kind": "post", "card_id": result["card"]["id"], "agent_id": agent["id"], "text": "card_created", "category": "card_created"} if agent else None
    await effects.run(app_state, [*result["effects"], *([line] if line else [])])
    return result["card"]


async def start(app_state: Any, card_id: int, args: Mapping[str, Any], *, by: str) -> Dict[str, Any]:
    agent = await _allow(by, "start", await _card(card_id), args)
    return (await _act(app_state, "start", card_id, {"agent_id": agent["id"]}, by))["card"]


async def queue(app_state: Any, card_id: int, args: Mapping[str, Any], *, by: str) -> Dict[str, Any]:
    await _allow(by, "queue", await _card(card_id), args)
    reason = " ".join((args.get("reason") or "").split())
    _no_secrets("reason", reason)
    return (await _act(app_state, "queue", card_id, {"reason": reason}, by))["card"]


async def handoff(app_state: Any, card_id: int, args: Mapping[str, Any], *, by: str) -> Dict[str, Any]:
    agent = await _allow(by, "handoff", await _card(card_id), args)
    _no_secrets("handoff", args.get("handoff"))
    sent = {"agent_id": agent["id"], "handoff": args.get("handoff"), "progress": args.get("progress")}
    return (await _act(app_state, "handoff", card_id, sent, by))["card"]


async def finish(app_state: Any, card_id: int, args: Mapping[str, Any], *, by: str) -> Dict[str, Any]:
    card = await _card(card_id)
    agent = await _allow(by, "finish", card, args)
    if agent is None:
        raise CardRefused("not_allowed", "only the agent holding a card finishes it")
    if card["column"] != "in_progress":
        raise CardRefused("not_in_progress", "only a card in progress is finished")
    how, result_text = (args.get("how_to_validate") or "").strip(), (args.get("result") or "").strip()
    if not how:
        raise CardRefused("no_how_to_validate", "write how to validate this card (steps the owner can run) before you finish it")
    if len(how) > MAX_FINISH_CHARS or not result_text or len(result_text) > MAX_FINISH_CHARS:
        raise CardRefused("bad_card", f"result and how_to_validate are required, at most {MAX_FINISH_CHARS} characters each")
    needs_owner, ask = args.get("needs_owner"), " ".join((args.get("owner_ask") or "").split())
    if needs_owner is not None and type(needs_owner) is not bool:
        raise CardRefused("bad_card", "needs_owner is true when the owner must answer, pick or do something before the card closes, else false")
    if needs_owner and (not ask or len(ask) > MAX_ASK_CHARS):
        raise CardRefused("bad_card", f"owner_ask is required with needs_owner true: what the owner must answer, pick or do, at most {MAX_ASK_CHARS} characters")
    if needs_owner:
        result_text = f"needs you: {ask}\n\n{result_text}"
    _no_secrets("finish", result_text, how)
    report_id: Optional[int] = None
    parent = await body.run_db(lambda c: store.get_agent(c, agent["parent_id"])) if agent["parent_id"] is not None else None
    if parent is not None and parent["torn_down_at"] is None:
        try:
            report_id = await reports.file(app_state, agent, result_text)
        except reports.ReportRefused as exc:
            raise CardRefused("report_pending", str(exc)) from None
    sent = {"result": result_text, "how_to_validate": how, "validate_link": args.get("validate_link"), "report_id": report_id}
    straight = needs_owner is False and card.get("parent") is None
    try:
        finished = (await _act(app_state, "finish", card_id, sent, by, skip=("review_entered",) if straight else ()))["card"]
    except Exception:  # noqa: BLE001
        if report_id is not None:
            await body.run_db(lambda c: store.delete_report(c, report_id))
        raise
    if not straight:
        return finished
    return await _close_done(app_state, card_id, "finished and validated by its agent", by) or finished


async def _close_done(app_state: Any, card_id: int, reason: str, by: str) -> Optional[Dict[str, Any]]:
    try:
        return (await _act(app_state, "done", card_id, {"reason": reason, "agent_close": True}, by))["card"]
    except CardRefused as exc:
        if exc.code not in _CLOSE_SKIPS:
            raise
        logger.info("swarm_card_agent_close_skipped", card_id=card_id, code=exc.code)
        return None


async def close(app_state: Any, card_id: int, args: Mapping[str, Any], *, by: str) -> Dict[str, Any]:
    card = await _card(card_id)
    if await _allow(by, "close", card, args) is None:
        raise CardRefused("not_allowed", "close is an agent's tool; the owner moves a card with the board")
    if card["column"] != "review":
        raise CardRefused("not_in_review", "only a card in Review is closed")
    reason = " ".join((args.get("reason") or "").split())
    if not reason or len(reason) > MAX_ASK_CHARS:
        raise CardRefused("bad_card", f"reason is required, at most {MAX_ASK_CHARS} characters")
    _no_secrets("reason", reason)
    return (await _act(app_state, "done", card_id, {"reason": reason, "agent_close": True}, by))["card"]


async def release(app_state: Any, card_id: int, args: Mapping[str, Any], *, by: str) -> Dict[str, Any]:
    await _allow(by, "release", await _card(card_id), args)
    return (await _act(app_state, "release", card_id, {"reason": args.get("reason", "")}, by))["card"]


async def _target(agent_id: Any, dealer: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    row = await body.run_db(lambda c: store.get_agent(c, int(agent_id))) if type(agent_id) is int else None
    if row is None or row["torn_down_at"] is not None:
        raise CardRefused("bad_agent", "that agent is not a live Swarm agent")
    if row.get("task_type") == _VALIDATION_TASK_TYPE:
        raise CardRefused("bad_agent", "a validation agent only validates; it is dealt no card")
    if dealer is not None and not await body.run_db(lambda c: _within(c, dealer["id"], row)):
        raise CardRefused("not_allowed", "you deal cards only to yourself and the agents under you")
    return row


def _within(conn: sqlite3.Connection, root_id: int, row: Mapping[str, Any]) -> bool:
    seen = set()
    while row is not None and row["id"] not in seen:
        if row["id"] == root_id:
            return True
        seen.add(row["id"])
        row = store.get_agent(conn, row["parent_id"]) if row["parent_id"] is not None else None
    return False


async def deal(app_state: Any, card_id: Optional[int], args: Mapping[str, Any], *, by: str, skip: Sequence[str] = ()) -> Dict[str, Any]:
    if args.get("hold"):
        held = await _card(card_id) if card_id is not None else None
        await dealer.answered(held, await _allow(by, "deal", held, args))
        return held or {}
    if card_id is None:
        top = await fit.top_card(await _agent(by))
        if top is None:
            raise CardRefused("bad_card", "card_id is required: you have no queued card of your own project to deal")
        card_id = int(top["id"])
    card = await _card(card_id)
    dealer_row = await _allow(by, "deal", card, args)
    target = await _target(args.get("agent_id"), dealer_row)
    if (card.get("holder") or {}).get("agent_id") is not None:
        return await swap(app_state, card_id, args, by=by)
    reason = " ".join((args.get("reason") or "").split())
    _no_secrets("reason", reason)
    misfit = await body.run_db(lambda c: fit.misfit(c, card, target)) if dealer_row is not None and not reason else None
    if misfit:
        raise CardRefused("not_fit", misfit)
    grants = (await capacity.grants_by_scope()) if target.get("state") == "asleep" else {}
    slot = await body.run_db(lambda c: deliver.slot_refusal(c, target, card.get("project_id"), grants))
    dealt = (await _act(app_state, "deal", card_id, {"agent_id": target["id"], "slot_ok": slot is None, "commit": bool(args.get("commit")),
                                                 "reason": reason},
                        by, skip=skip))["card"]
    await dealer.answered(dealt, dealer_row)
    return dealt


async def swap(app_state: Any, card_id: int, args: Mapping[str, Any], *, by: str) -> Dict[str, Any]:
    card = await _card(card_id)
    dealer = await _allow(by, "swap", card, args)
    target = await _target(args.get("agent_id"), dealer)
    return (await _act(app_state, "swap", card_id, {"agent_id": target["id"]}, by))["card"]


async def move(app_state: Any, card_id: int, args: Mapping[str, Any], *, by: str) -> Dict[str, Any]:
    await _allow(by, "move", await _card(card_id), args)
    sent = {"before_id": args.get("before_id"), "pin_place": bool(args.get("pin_place")), "reason": "moved by the owner"}
    return (await _act(app_state, "move", card_id, sent, by))["card"]


async def reorder(app_state: Any, card_id: int, args: Mapping[str, Any], *, by: str) -> Dict[str, Any]:
    card = await _card(card_id)
    agent = await _allow(by, "reorder", card, args)
    if agent is None:
        return await move(app_state, card_id, args, by=by)
    rule = (await card_port.get().policy_read("rules", {"list_keys": [card["list_key"]]}))["rules"][card["list_key"]]["reorder"]
    sent = {"before_id": args.get("before_id"), "reason": (args.get("reason") or "").strip()}
    if rule == "auto":
        return (await _act(app_state, "move", card_id, sent, by))["card"]
    return (await _act(app_state, "suggest", card_id, {**sent, "agent_id": agent["id"]}, by))["card"]


async def _cascade(app_state: Any, op: str, card_id: int, args: Mapping[str, Any], by: str) -> Dict[str, Any]:
    await _allow(by, op, await _card(card_id), args)
    result = await _act(app_state, op, card_id, args, by)
    return {"card": result["card"], "cascaded": result["data"].get("cascaded", []), "agents": result["data"].get("agents", [])}


async def pause(app_state: Any, card_id: int, args: Mapping[str, Any], *, by: str) -> Dict[str, Any]:
    return await _cascade(app_state, "pause", card_id, {"mode": args["mode"]}, by)


async def resume(app_state: Any, card_id: int, args: Mapping[str, Any], *, by: str) -> Dict[str, Any]:
    return await _cascade(app_state, "resume", card_id, {}, by)


async def pin(app_state: Any, card_id: int, args: Mapping[str, Any], *, by: str) -> Dict[str, Any]:
    await _allow(by, "pin", await _card(card_id), args)
    agent_id = args.get("agent_id")
    if agent_id is not None:
        await _target(agent_id)
    return (await _act(app_state, "pin", card_id, {"agent_id": agent_id, "place": bool(args.get("place"))}, by))["card"]


async def done(app_state: Any, card_id: int, args: Mapping[str, Any], *, by: str) -> Dict[str, Any]:
    await _allow(by, "done", await _card(card_id), args)
    return (await _act(app_state, "done", card_id, {"expected_revision": args.get("expected_revision")}, by))["card"]


async def _live_last_holder(card: Mapping[str, Any]) -> Optional[int]:
    last = card.get("last_holder")
    row = await body.run_db(lambda c: store.get_agent(c, int(last))) if last is not None else None
    return row["id"] if row and row["torn_down_at"] is None else None


async def void_report(card: Mapping[str, Any]) -> bool:
    report_id = card.get("report_id")
    return report_id is not None and await body.run_db(lambda c: store.decide_report(c, report_id, "rejected"))


async def restore_report(card: Mapping[str, Any], voided: bool) -> None:
    if voided:
        await body.run_db(lambda c: store.decide_report(c, card["report_id"], "pending", expected="rejected"))


async def send_back(app_state: Any, card_id: int, args: Mapping[str, Any], *, by: str) -> Dict[str, Any]:
    card = await _card(card_id)
    await _allow(by, "send_back", card, args)
    if card["column"] != "review":
        raise CardRefused("not_in_review", "that card is not in review")
    note = (args.get("note") or "").strip()
    if not note or len(note) > 4000:
        raise CardRefused("bad_card", "the note is required, at most 4000 characters")
    voided = await void_report(card)
    try:
        result = await _act(app_state, "send_back", card_id, {"note": note, "rehold": await _live_last_holder(card)}, by)
    except Exception:  # noqa: BLE001
        await restore_report(card, voided)
        raise
    holder = (result["card"].get("holder") or {}).get("agent_id")
    if holder is not None:
        text = texts.tell_text("sent_back", result["card"])
        await deliver.tell(app_state, holder, text or "", ref=f"card:{card_id}")
        try:
            await owner_message.post_owner_message(app_state, holder, note)
        except (body.BodyError, sqlite3.Error, OSError) as exc:
            logger.warning("swarm_card_send_back_note_failed", card_id=card_id, error_type=type(exc).__name__)
    return result["card"]


async def settle_suggestion(app_state: Any, card_id: Optional[int], args: Mapping[str, Any], *, by: str) -> Dict[str, Any]:
    await _allow(by, "settle_suggestion", None, args)
    result = await card_port.get().policy("settle_suggestion", {"suggestion_id": args["suggestion_id"], "action": args["action"]}, by)
    await effects.run(app_state, result["effects"])
    return {"suggestion": result["data"]["suggestion"], "card": result["card"]}


async def set_rules(app_state: Any, card_id: Optional[int], args: Mapping[str, Any], *, by: str) -> Dict[str, Any]:
    await _allow(by, "set_rules", None, args)
    result = await card_port.get().policy("set_rules", {"list_key": args["list_key"], "changes": args["changes"]}, by)
    await effects.run(app_state, result["effects"])
    return result["data"]["rules"]


def _card_text(value: str, limit: int) -> str:
    return "".join(ch for ch in value if ord(ch) >= 32 or ch in "\n\t").strip()[:limit]


async def mint_for_spawn(app_state: Any, parent: Mapping[str, Any], child: Mapping[str, Any], *, title: str, text: str,
                         card_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    by = f"agent:{parent['id']}"
    if card_id is None:
        list_key = str(parent["project_id"]) if parent.get("project_id") is not None else parent["thread_key"]
        try:
            made = await create(app_state, None, {"title": _card_text(title, MAX_TITLE_CHARS) or "spawned work", "text": _card_text(text, MAX_CARD_TEXT),
                                                  "list_key": list_key, "queued": True}, by=by, origin=f"spawn:{parent['id']}")
        except CardRefused as exc:
            if exc.code != "refused":
                raise
            logger.warning("swarm_card_spawn_mint_refused", parent_id=parent["id"], child_id=child["id"], error=str(exc)[:200])
            return None
        card_id = made["id"]
    else:
        taken = await _card(card_id)
        if taken["column"] not in ("todo", "in_progress") or (taken.get("holder") or {}).get("agent_id") is not None:
            raise CardRefused("held", f"card #{card_id} is no longer waiting in the queue")
    return await deal(app_state, card_id, {"agent_id": child["id"], "commit": True}, by=by, skip=("tell",))


async def held_cards(agent_id: int) -> List[Dict[str, Any]]:
    return await card_port.get().cards(holder=agent_id, columns=["in_progress"])




async def set_column(app_state: Any, card_id: int, args: Mapping[str, Any], *, by: str) -> Dict[str, Any]:
    before = await _card(card_id)
    await _allow(by, "set_column", before, args)
    target = args.get("column")
    if target not in COLUMNS:
        raise CardRefused("bad_card", f"column must be one of {', '.join(COLUMNS)}")
    note = (args.get("note") or "").strip()
    _no_secrets("note", note)
    if before["state"] == "open" and target in ("todo", "in_progress"):
        result = await _act(app_state, "set_lane", card_id, {"queued": target == "in_progress"}, by, skip=("tell", "interrupt"))
    else:
        result = await _act(app_state, "set_column", card_id, {"column": target}, by, skip=("tell", "interrupt"))
    card = result["card"]
    if note:
        card = (await _act(app_state, "owner_note", card_id, {"note": note}, by))["card"]
    notices.note(app_state, before, card, owner_note=note)
    return card


async def archive(app_state: Any, card_id: int, args: Mapping[str, Any], *, by: str) -> Dict[str, Any]:
    before = await _card(card_id)
    await _allow(by, "archive", before, args)
    card = (await _act(app_state, "archive", card_id, {"on": bool(args.get("on"))}, by))["card"]
    notices.note(app_state, before, card)
    return card


async def delete(app_state: Any, card_id: int, args: Mapping[str, Any], *, by: str) -> Dict[str, Any]:
    before = await _card(card_id)
    await _allow(by, "delete", before, args)
    await card_port.get().act("delete", card_id, {}, by)
    notices.note(app_state, before, None)
    return {"id": int(card_id), "deleted": True}


async def curate_check(card_id: int, args: Mapping[str, Any], *, by: str, op: str) -> Dict[str, Any]:
    card = await _card(card_id)
    if await _allow(by, op, card, args) is None:
        raise CardRefused("not_allowed", "this is an agent's tool; the owner archives and deletes cards on the board")
    reason = " ".join((args.get("reason") or "").split())
    if not reason or len(reason) > MAX_ASK_CHARS:
        raise CardRefused("bad_card", f"reason is required, at most {MAX_ASK_CHARS} characters")
    _no_secrets("reason", reason)
    return {"card": card, "reason": reason}


async def agent_archive(app_state: Any, card_id: int, args: Mapping[str, Any], *, by: str) -> Dict[str, Any]:
    checked = await curate_check(card_id, args, by=by, op="agent_archive")
    card = (await _act(app_state, "archive", card_id, {"on": True, "reason": checked["reason"]}, by))["card"]
    notices.note(app_state, checked["card"], card)
    return card


async def agent_delete(app_state: Any, card_id: int, args: Mapping[str, Any], *, by: str) -> Dict[str, Any]:
    checked = await curate_check(card_id, args, by=by, op="agent_delete")
    await card_port.get().act("delete", card_id, {"reason": f"{by}: {checked['reason']}"}, "owner")
    notices.note(app_state, checked["card"], None)
    return {"id": int(card_id), "deleted": True}


async def auto_promote(app_state: Any, card_id: int, args: Mapping[str, Any], *, by: str) -> Dict[str, Any]:
    await _allow(by, "auto_promote", await _card(card_id), args)
    return (await _act(app_state, "auto_promote", card_id, {"on": bool(args.get("on"))}, by))["card"]
