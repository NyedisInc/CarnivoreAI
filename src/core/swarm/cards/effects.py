
from __future__ import annotations

import asyncio
import sqlite3
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Sequence

import structlog

from src.core import db
from src.core.swarm import body, facts, fact_index, memory, push, store, switch, thread_port
from src.core.swarm.cards import deliver, port as card_port, texts
from src.core.swarm.names import shown_name
from src.cplugs.sdk.cards import CardRefused

logger = structlog.get_logger()

_ERRORS = (body.BodyError, memory.SwarmFileError, facts.FactRefused, fact_index.Fts5Missing, sqlite3.Error,
           db.DatastoreUnreadableError, OSError, RuntimeError, CardRefused, ValueError)
AUTO_DONE_SKIPS = ("pass_changed", "task_manager_lane")


_OFF_SKIPS = frozenset({"learn", "retire_validator"})


_NO_WAKE = frozenset({"pause_after_step", "pause_now", "owner_release", "lapse_stop"})


async def _agent(agent_id: Optional[int]) -> Optional[Dict[str, Any]]:
    if agent_id is None:
        return None
    return await body.run_db(lambda c: store.get_agent(c, int(agent_id)))


async def _name(agent_id: Optional[int], fallback: str) -> str:
    agent = await _agent(agent_id)
    return shown_name(agent) if agent else fallback


async def _project_name(project_id: Optional[int]) -> str:
    if project_id is None:
        return "this project"
    row = await body.run_db(lambda c: c.execute("SELECT display_name FROM projects WHERE id = ?", (project_id,)).fetchone())
    return row["display_name"] if row else "this project"


async def _chat_context(card: Mapping[str, Any], effect: Mapping[str, Any]) -> Dict[str, Any]:
    data = dict(effect.get("data") or {})
    port = card_port.get()
    ctx: Dict[str, Any] = dict(data)
    ctx["agent"] = await _name(effect.get("agent_id"), "an agent")
    if data.get("old") is not None:
        ctx["old"] = await _name(data["old"], "an agent")
    if "dealer" in data:
        ctx["dealer"] = await _name(data["dealer"], "the owner")
    if data.get("other") is not None:
        other = await port.card(int(data["other"]))
        ctx["other_title"] = other["title"] if other else f"card #{data['other']}"
    if data.get("agents"):
        ctx["agent_names"] = [await _name(i, f"agent {i}") for i in data["agents"]]
    if effect.get("text") == "stalled":
        ctx["project"] = await _project_name(card.get("project_id"))
    return ctx


async def _chain_facts(agent_id: int, card: Mapping[str, Any]) -> List[Dict[str, str]]:
    return await facts.chain_facts_for(agent_id, f"{card.get('title') or ''} {card.get('text') or ''}")


async def _tell(app_state: Any, card: Mapping[str, Any], effect: Mapping[str, Any]) -> None:
    names: Dict[str, Any] = {"proof": card.get("proof") or ""}
    to = (effect.get("data") or {}).get("to")
    if to is not None:
        names["agent"] = await _name(to, "another agent")
    if effect["text"] == "dealt" and effect.get("agent_id") is not None:
        names["chain_facts"] = await _chain_facts(int(effect["agent_id"]), card)
        names["note"] = (effect.get("data") or {}).get("note") or ""
    text = texts.tell_text(effect["text"], card, **names)
    if text is None or effect.get("agent_id") is None:
        logger.warning("swarm_card_effect_skipped", kind="tell", text=effect.get("text"))
        return
    await deliver.tell(app_state, int(effect["agent_id"]), text, ref=f"card:{card['id']}", wake=effect["text"] not in _NO_WAKE)


async def _interrupt(app_state: Any, card: Mapping[str, Any], effect: Mapping[str, Any]) -> None:
    if effect.get("agent_id") is not None:
        await deliver.interrupt(app_state, int(effect["agent_id"]), ref=f"card_pause:{card['id']}")


async def _post(app_state: Any, card: Mapping[str, Any], effect: Mapping[str, Any]) -> None:
    thread = thread_port.get()
    line = texts.post_text(effect["text"], card, await _chat_context(card, effect))
    if thread is None or line is None:
        return
    key = str(card["list_key"])
    await thread.post_traffic(key, line, f"card:{effect.get('category') or effect['text']}:{card['id']}")
    await asyncio.to_thread(push.notify_thread, key)


async def _rollup(app_state: Any, card: Mapping[str, Any], effect: Mapping[str, Any]) -> None:
    result = await card_port.get().act("rollup", int(effect["card_id"]), {}, "server")
    await run(app_state, result["effects"])


async def auto_done(app_state: Any, card_id: int, *, passed: bool = False) -> None:
    port = card_port.get()
    live = await port.card(card_id)
    if live is None or live["column"] != "review" or live["parent"] is not None:
        return
    rules = (await port.policy_read("rules", {"list_keys": [live["list_key"]]}))["rules"][live["list_key"]]
    if not rules["auto_done"] or (rules["auto_validate"] and not passed):
        return
    args: Dict[str, Any] = {}
    if passed:
        record = live.get("validation") or {}
        if (live.get("mark") or {}).get("name") != "validated" or record.get("verdict") != "pass":
            return
        args["expect_pass"] = {key: record.get(key) for key in ("agent_id", "started_at", "finished_at")}
    try:
        result = await port.act("done", live["id"], args, "auto_done")
    except CardRefused as exc:
        if exc.code not in AUTO_DONE_SKIPS:
            raise
        logger.info("swarm_card_auto_done_skipped", card_id=live["id"], code=exc.code)
        return
    await run(app_state, result["effects"])


async def _review_entered(app_state: Any, card: Mapping[str, Any], effect: Mapping[str, Any]) -> None:
    from src.core.swarm.cards import validate

    port = card_port.get()
    live = await port.card(int(effect["card_id"]))
    if live is None or live["column"] != "review" or live["parent"] is not None:
        return
    rules = (await port.policy_read("rules", {"list_keys": [live["list_key"]]}))["rules"][live["list_key"]]
    if rules["auto_validate"]:
        try:
            await validate.start(app_state, live["id"], by="auto_validate")
        except CardRefused as exc:
            logger.info("swarm_card_auto_validate_skipped", card_id=live["id"], code=exc.code)
        return
    await auto_done(app_state, live["id"])


async def _retire_validator(app_state: Any, card: Mapping[str, Any], effect: Mapping[str, Any]) -> None:
    from src.core.swarm.cards import validate

    if effect.get("agent_id") is not None:
        await validate.retire_now(app_state, int(effect["agent_id"]))


async def _learn(app_state: Any, card: Mapping[str, Any], effect: Mapping[str, Any]) -> None:
    project_id = card.get("project_id")
    agent = await body.run_db(lambda c: store.get_project_agent(c, project_id)) if project_id is not None else None
    if agent is None or not effect.get("ref"):
        return
    note, ref, title = effect["text"], effect["ref"], f"send-back on {card['title']}"
    done = await body.run_db(lambda c: facts.store_owner_fact(c, agent, title=title, text=note, owner_message_ref=ref))
    thread = thread_port.get()
    line = texts.post_text("learned", card, {"fact_id": done["fact_id"]}) if done.get("kind") == "rule" else None
    if thread is not None and line is not None:
        await thread.post_traffic(agent["thread_key"], line, f"card:learned:{card['id']}")
    await asyncio.to_thread(push.notify_agent, agent["id"])


_HANDLERS: Dict[str, Callable[[Any, Mapping[str, Any], Mapping[str, Any]], Awaitable[None]]] = {
    "tell": _tell, "interrupt": _interrupt, "post": _post, "rollup": _rollup, "review_entered": _review_entered, "learn": _learn,
    "retire_validator": _retire_validator,
}


async def run(app_state: Any, effects: Sequence[Mapping[str, Any]]) -> None:
    try:
        port = card_port.get()
    except card_port.CardsOff:
        logger.warning("swarm_card_effects_dropped", count=len(effects))
        return
    for effect in effects:
        handler = _HANDLERS.get(effect.get("kind", ""))
        if handler is None:
            logger.warning("swarm_card_effect_unknown", kind=effect.get("kind"))
            continue
        if effect.get("kind") in _OFF_SKIPS and not switch.is_on():
            logger.info("swarm_card_effect_skipped_off", kind=effect.get("kind"), card_id=effect.get("card_id"))
            continue
        try:
            card = await port.card(int(effect["card_id"]))
            if card is None:
                continue
            await handler(app_state, card, effect)
        except _ERRORS as exc:
            logger.warning("swarm_card_effect_failed", kind=effect.get("kind"), card_id=effect.get("card_id"), error_type=type(exc).__name__)
