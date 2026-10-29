
from __future__ import annotations

import asyncio
import sqlite3
from typing import Any, Dict, Optional

import structlog

from src.core import db
from src.core.mcp.caller import AgentCaller
from src.core.swarm import activity, body, delivery, memory, push, say, spawn, promotion_store, store, teardown, thread_port
from src.core.swarm.cards import effects as card_effects, port as card_port
from src.cplugs.sdk.cards import CardRefused

logger = structlog.get_logger()

REPORT_PREFIX = "report:"
MAX_REPORT_CHARS = 4000
MAX_DONE_ITEMS = 40
CARD_TEXT_CHARS = 2000
MAX_NOTE_CHARS = 1000
DECISIONS = ("accept", "reject")
_ACT_ERRORS = (body.BodyError, memory.SwarmFileError, OSError, sqlite3.Error, db.DatastoreUnreadableError, CardRefused)


class ReportRefused(ValueError):
    pass


async def _caller_agent(view: Any, caller: AgentCaller) -> Dict[str, Any]:
    try:
        return await spawn.parent_agent(view, caller)
    except spawn.SpawnRefused as exc:
        raise ReportRefused(str(exc)) from None


def report_text(args: Dict[str, Any]) -> str:
    summary = args.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ReportRefused("summary is required")
    items = args.get("done_items") or []
    if not isinstance(items, list) or len(items) > MAX_DONE_ITEMS or not all(isinstance(i, str) for i in items):
        raise ReportRefused(f"done_items must be a list of at most {MAX_DONE_ITEMS} strings")
    text = summary.strip() + ("\n\ndone:\n" + "\n".join(f"- {i.strip()}" for i in items if i.strip()) if items else "")
    if len(text) > MAX_REPORT_CHARS:
        raise ReportRefused(f"the report must be at most {MAX_REPORT_CHARS} characters")
    try:
        memory.refuse_secrets(text, "report")
    except memory.SwarmFileError as exc:
        raise ReportRefused(str(exc)) from None
    return text


async def _tell(app_state: Any, agent_id: int, text: str, ref: str) -> None:
    try:
        if await delivery.deliver_text(app_state, agent_id, text, source="report", authority="data", source_ref=ref) == "refused:asleep":
            await body.wake(app_state, agent_id, "crosstalk", "data", orders=text)
    except (body.BodyError, sqlite3.Error, db.DatastoreUnreadableError, OSError, RuntimeError) as exc:
        logger.warning("swarm_report_tell_failed", agent_id=agent_id, ref=ref, error_type=type(exc).__name__)


async def file(app_state: Any, agent: Dict[str, Any], text: str) -> int:
    if agent["parent_id"] is None:
        raise ReportRefused("you have no parent to report to")
    port = thread_port.get()
    if port is None:
        raise ReportRefused("the huddle plugin is off, so there is nowhere to post the report")
    parent = await body.run_db(lambda c: store.get_agent(c, agent["parent_id"]))
    waiting = await body.run_db(lambda c: store.list_reports(c, agent_id=agent["id"]))
    if parent is None or parent["torn_down_at"] is not None:
        raise ReportRefused("your parent is gone")
    if waiting:
        raise ReportRefused(f"report {waiting[0]['id']} is still waiting for {parent['display_name']} to accept it")
    report_id = await body.run_db(lambda c: store.create_report(c, agent, text))
    ref = f"{REPORT_PREFIX}{report_id}"
    card_text = text if len(text) <= CARD_TEXT_CHARS else text[:CARD_TEXT_CHARS - 3].rstrip() + "..."
    try:
        item = await port.post_card(agent["thread_key"], "done", f"report: {agent['job'][:80]}", card_text, ref)
        if card_text != text:
            await say.post_as_agent(agent, text)
        line = await port.post_traffic(parent["thread_key"], f"{agent['display_name']} reported: {text.splitlines()[0][:200]}", ref)
    except Exception as exc:  # noqa: BLE001
        await body.run_db(lambda c: store.delete_report(c, report_id))
        logger.warning("swarm_report_post_failed", report_id=report_id, error_type=type(exc).__name__)
        raise ReportRefused("the report could not be posted in the threads; try again") from None
    await body.run_db(lambda c: store.set_report_cards(c, report_id, str(item), line))
    for key in (agent["thread_key"], parent["thread_key"]):
        await asyncio.to_thread(push.notify_thread, key)
    await _tell(app_state, parent["id"],
                f"{agent['display_name']} reported (report {report_id}). Review it, then call swarm_accept_report "
                f"with report_id {report_id}.\n\n{text}", ref)
    activity.mark(agent["id"], "done")
    logger.info("swarm_reported", report_id=report_id, agent_id=agent["id"], parent_id=parent["id"])
    return report_id


async def report(view: Any, caller: AgentCaller, args: Dict[str, Any]) -> Dict[str, Any]:
    agent = await _caller_agent(view, caller)
    if agent["parent_id"] is None:
        raise ReportRefused("you have no parent to report to")
    return {"report_id": await file(view.app.state, agent, report_text(args)), "state": "pending"}


async def accept(view: Any, caller: AgentCaller, args: Dict[str, Any]) -> Dict[str, Any]:
    agent = await _caller_agent(view, caller)
    report_id, decision, note = args.get("report_id"), args.get("decision"), args.get("note") or ""
    if type(report_id) is not int or report_id < 1:
        raise ReportRefused("report_id is required and must be a positive whole number")
    if decision not in DECISIONS:
        raise ReportRefused("decision must be accept or reject")
    if not isinstance(note, str) or len(note) > MAX_NOTE_CHARS:
        raise ReportRefused(f"note must be text of at most {MAX_NOTE_CHARS} characters")
    found = await body.run_db(lambda c: store.get_report(c, report_id))
    if found is None or found["parent_id"] != agent["id"]:
        raise ReportRefused("that report is not from one of your own agents")
    return await decide(view.app.state, agent, found, decision, note)


async def decide(app_state: Any, agent: Dict[str, Any], found: Dict[str, Any], decision: str, note: str = "") -> Dict[str, Any]:
    report_id = found["id"]
    new = "accepted" if decision == "accept" else "rejected"
    if not await body.run_db(lambda c: store.decide_report(c, report_id, new)):
        raise ReportRefused(f"report {report_id} was already decided")
    child = await body.run_db(lambda c: store.get_agent(c, found["agent_id"]))
    outcome = "rejected"
    try:
        card = await _card_of(report_id)
        if decision == "reject":
            if card is not None and card.get("column") == "review":
                live = child is not None and child["torn_down_at"] is None
                await _card_act(app_state, "reject", card["id"], {"rehold": child["id"] if live else None}, agent)
            if child is not None and child["torn_down_at"] is None:
                await _tell(app_state, child["id"], f"Your report {report_id} was not accepted. {note.strip() or 'No reason given.'}",
                            f"{REPORT_PREFIX}{report_id}")
        elif child is not None and child["torn_down_at"] is None:
            if _awaits_acceptance(card):
                await _card_act(app_state, "accept_child", card["id"], {"by_agent": agent["id"], "report_id": report_id}, agent)
            outcome = await _act_on_child(app_state, child, found)
        else:
            if _awaits_acceptance(card):
                await _card_act(app_state, "accept_child", card["id"], {"by_agent": agent["id"], "report_id": report_id}, agent)
            outcome = "torn_down"
    except _ACT_ERRORS as exc:
        await body.run_db(lambda c: store.decide_report(c, report_id, "pending", expected=new))
        logger.warning("swarm_accept_failed", report_id=report_id, error_type=type(exc).__name__, error=str(exc)[:200])
        raise ReportRefused(f"report {report_id} stays pending: {exc}") from None
    logger.info("swarm_report_decided", report_id=report_id, decision=decision, outcome=outcome)
    return {"report_id": report_id, "decision": decision, "agent_id": found["agent_id"], "outcome": outcome}


async def _card_of(report_id: int) -> Optional[Dict[str, Any]]:
    try:
        return await card_port.get().card_for_report(report_id)
    except card_port.CardsOff:
        return None


def _awaits_acceptance(card: Optional[Dict[str, Any]]) -> bool:
    return card is not None and card.get("parent") is not None and card.get("column") == "review"


async def _card_act(app_state: Any, op: str, card_id: int, args: Dict[str, Any], parent: Dict[str, Any]) -> None:
    result = await card_port.get().act(op, card_id, args, f"agent:{parent['id']}")
    await card_effects.run(app_state, result["effects"])


async def _act_on_child(app_state: Any, child: Dict[str, Any], found: Dict[str, Any]) -> str:
    candidate = child["rank"] == "task" and await body.run_db(lambda c: promotion_store.promotion_earned(c, child))
    if child["rank"] == "task" and not candidate:
        await teardown.run(app_state, child)
        return "torn_down"
    await body.sleep(app_state, child["id"], "sleep")
    port = thread_port.get()
    if port is not None and (found.get("child_card_ref") or "").isdigit():
        try:
            await port.close_card(int(found["child_card_ref"]), "done")
        except Exception as exc:  # noqa: BLE001
            logger.warning("swarm_report_card_not_closed", report_id=found["id"], error_type=type(exc).__name__)
    return "promotion_candidate" if candidate else "asleep"
