
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from typing import Any, Dict, List, Optional

import structlog

from src.core import db
from src.core.db import transaction
from src.core.mcp.caller import AgentCaller
from src.core.swarm import body, fact_life, facts, memory, push, receipts, routing, thread_port
from src.core.swarm.routing import QuestionRefused
from src.core.trail_entry import utc_now
from src.core.swarm.names import shown_name

logger = structlog.get_logger()

MAX_ANSWER_CHARS = 4000
MAX_REASON_CHARS = 500
OWNER_REF = re.compile(r"huddle:msg:[0-9]+")
_DB_ERRORS = (sqlite3.Error, db.DatastoreUnreadableError, OSError)


def _qid(args: Dict[str, Any]) -> int:
    value = args.get("question_id")
    if type(value) is not int or value < 1:
        raise QuestionRefused("question_id is required and must be a positive whole number")
    return value


def _hop_of(conn: sqlite3.Connection, agent: Dict[str, Any], question_id: int) -> sqlite3.Row:
    q = conn.execute("SELECT state FROM swarm_questions WHERE id = ?", (question_id,)).fetchone()
    last = conn.execute("SELECT * FROM swarm_question_hops WHERE question_id = ? ORDER BY id DESC LIMIT 1",
                        (question_id,)).fetchone()
    if q is None or q["state"] not in routing.WALKING or last is None or last["agent_id"] != agent["id"] \
            or last["outcome"] != "timeout":
        raise QuestionRefused("that question was not routed to you, or it already moved on")
    return last


def _quote(text: str) -> str:
    return "\n".join("> " + line for line in text.splitlines()) or "> "


def _apply_answer(conn: sqlite3.Connection, agent: Dict[str, Any], question_id: int, text: str,
                  fact_ids: List[Any]) -> Dict[str, Any]:
    with transaction(conn):
        hop = _hop_of(conn, agent, question_id)
        receipt = receipts.build(conn, agent, fact_ids)
        now = utc_now()
        conn.execute("UPDATE swarm_question_hops SET outcome = 'answered', at = ? WHERE id = ?", (now, hop["id"]))
        conn.execute("UPDATE swarm_questions SET state = 'answered', answer_text = ?, answered_by = ?, answered_at = ? "
                     "WHERE id = ?", (text, f"agent:{agent['id']}", now, question_id))
        receipts.save(conn, question_id, agent["id"], receipt)
        key = fact_life.conversation_key(conn, agent["id"])
        for fact_id in receipt.fact_ids:
            fact_life.record_use(conn, fact_id, key, now)
    question = conn.execute("SELECT text FROM swarm_questions WHERE id = ?", (question_id,)).fetchone()[0]
    return {"question": question, "receipt": receipt, "askers": routing.askers_of(conn, question_id)}


async def answer(view: Any, caller: AgentCaller, args: Dict[str, Any]) -> Dict[str, Any]:
    agent = await routing.caller_agent(view, caller)
    qid, text, ids = _qid(args), args.get("text"), args.get("fact_ids") or []
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_ANSWER_CHARS:
        raise QuestionRefused(f"text is required, at most {MAX_ANSWER_CHARS} characters")
    if not isinstance(ids, list):
        raise QuestionRefused("fact_ids must be a list of fact ids")
    try:
        memory.refuse_secrets(text, "answer")
    except memory.SwarmFileError as exc:
        raise QuestionRefused(str(exc)) from None
    try:
        done = await body.run_db(lambda c: _apply_answer(c, agent, qid, text.strip(), ids))
    except _DB_ERRORS as exc:
        logger.warning("swarm_answer_failed", question_id=qid, error_type=type(exc).__name__)
        raise QuestionRefused("the answer could not be saved; try again") from None
    receipt = done["receipt"]
    message = (f'{shown_name(agent)} answered your question "{done["question"][:300]}":\n\n{_quote(text.strip())}\n\n'
               f"Receipt (written by the server): {receipt.rendered}.")
    sent = 0
    for asker in done["askers"]:
        if await routing.tell(view.app.state, asker["id"], message, source="swarm_answer", authority="data",
                              ref=f"question:{qid}", reason="crosstalk"):
            sent += 1
        await asyncio.to_thread(push.notify_agent, asker["id"])
    await asyncio.to_thread(push.notify_agent, agent["id"])
    logger.info("swarm_answered", question_id=qid, agent_id=agent["id"], kind=receipt.kind, kept=len(receipt.fact_ids))
    return {"question_id": qid, "state": "answered", "receipt": receipt.rendered, "kind": receipt.kind,
            "fact_ids": receipt.fact_ids, "delivered_to": sent}


def _apply_pass(conn: sqlite3.Connection, agent: Dict[str, Any], question_id: int) -> None:
    with transaction(conn):
        hop = _hop_of(conn, agent, question_id)
        conn.execute("UPDATE swarm_question_hops SET outcome = 'passed', at = ? WHERE id = ?", (utc_now(), hop["id"]))


async def pass_up(view: Any, caller: AgentCaller, args: Dict[str, Any]) -> Dict[str, Any]:
    agent = await routing.caller_agent(view, caller)
    qid, reason = _qid(args), args.get("reason") or ""
    if not isinstance(reason, str) or len(reason) > MAX_REASON_CHARS:
        raise QuestionRefused(f"reason must be text of at most {MAX_REASON_CHARS} characters")
    try:
        await body.run_db(lambda c: _apply_pass(c, agent, qid))
        await routing.advance(view.app.state, qid)
        state = await body.run_db(lambda c: c.execute("SELECT state FROM swarm_questions WHERE id = ?", (qid,)).fetchone()[0])
    except _DB_ERRORS as exc:
        logger.warning("swarm_pass_failed", question_id=qid, error_type=type(exc).__name__)
        raise QuestionRefused("the pass could not be saved; try again") from None
    await asyncio.to_thread(push.notify_agent, agent["id"])
    logger.info("swarm_passed", question_id=qid, agent_id=agent["id"], reason=reason[:80])
    return {"question_id": qid, "state": state}


def _apply_owner_answer(conn: sqlite3.Connection, question_id: int, text: str, owner_message_ref: str) -> Dict[str, Any]:
    with transaction(conn):
        q = conn.execute("SELECT * FROM swarm_questions WHERE id = ?", (question_id,)).fetchone()
        if q is None or q["state"] != "open":
            raise QuestionRefused("that question is not waiting for the owner")
        now = utc_now()
        conn.execute("UPDATE swarm_questions SET state = 'answered', answer_text = ?, answered_by = 'owner', "
                     "answer_message_ref = ?, answered_at = ? WHERE id = ?", (text, owner_message_ref, now, question_id))
        askers = routing.askers_of(conn, question_id)
        tiers: Dict[int, Dict[str, Any]] = {}
        for asker in askers:
            for tier in routing.chain_for(conn, asker):
                tiers.setdefault(tier["id"], tier)
        for tier_id in tiers:
            conn.execute("INSERT INTO swarm_learning (agent_id, question_id, kind, text, owner_message_ref, state, created_at) "
                         "VALUES (?, ?, 'sealed_answer', ?, ?, 'queued', ?)", (tier_id, question_id, text, owner_message_ref, now))
    return {"question": dict(q), "askers": askers, "tiers": list(tiers)}


async def owner_answer(app_state: Any, question_id: int, decision: str, text: str, owner_message_ref: str, *,
                       structured: Optional[Dict[str, Any]] = None) -> bool:
    if decision != "answer" or not text.strip():
        logger.info("swarm_question_card_not_answered", question_id=question_id, decision=decision)
        return False
    if not OWNER_REF.fullmatch(owner_message_ref or ""):
        raise QuestionRefused("an owner answer needs the owner's message")
    done = await body.run_db(lambda c: _apply_owner_answer(c, question_id, text, owner_message_ref))
    port = thread_port.get()
    shown = (f"The owner answered your question {question_id} (his message {owner_message_ref}, attached by the server):"
             f"\n\n{text}")
    if structured:
        shown += "\n\nThe same answers as JSON, keyed by your question ids:\n" + json.dumps(structured, ensure_ascii=False)
    for asker in done["askers"]:
        try:
            if port is not None:
                await port.post_owner_message(asker["thread_key"], text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("swarm_owner_answer_post_failed", agent_id=asker["id"], error_type=type(exc).__name__)
        await routing.tell(app_state, asker["id"], shown, source="swarm_answer", authority="owner", ref=f"question:{question_id}",
                           reason="owner_message", owner_message_ref=owner_message_ref)
        await asyncio.to_thread(push.notify_agent, asker["id"])
    card = done["question"]["card_ref"]
    if port is not None and (card or "").isdigit():
        try:
            await port.close_card(int(card), "answered")
        except Exception as exc:  # noqa: BLE001
            logger.warning("swarm_question_card_not_closed", question_id=question_id, error_type=type(exc).__name__)
    for tier_id in done["tiers"]:
        await asyncio.to_thread(push.notify_agent, tier_id)
    logger.info("swarm_owner_answered", question_id=question_id, askers=len(done["askers"]), tiers=len(done["tiers"]))
    return True


def _reopen(conn: sqlite3.Connection, killed: facts.KillResult) -> List[Dict[str, Any]]:
    reopened = []
    with transaction(conn):
        for qid in killed.cited_question_ids:
            q = conn.execute("SELECT * FROM swarm_questions WHERE id = ?", (qid,)).fetchone()
            last = conn.execute("SELECT fact_ids FROM swarm_receipts WHERE question_id = ? ORDER BY id DESC LIMIT 1", (qid,)).fetchone()
            if q is None or q["state"] != "answered" or not str(q["answered_by"]).startswith("agent:") \
                    or last is None or killed.fact["id"] not in json.loads(last["fact_ids"]):
                continue
            conn.execute("UPDATE swarm_questions SET state = 'reopened', answer_text = NULL, answered_by = NULL, "
                         "answer_message_ref = NULL, answered_at = NULL WHERE id = ?", (qid,))
            reopened.append({"id": qid, "text": q["text"], "askers": routing.askers_of(conn, qid)})
    return reopened


async def kill_fact(app_state: Any, fact_id: str) -> List[int]:
    killed = await body.run_db(lambda c: facts.kill(c, fact_id))
    reopened = await body.run_db(lambda c: _reopen(c, killed))
    port = thread_port.get()
    for q in reopened:
        for asker in q["askers"]:
            try:
                if port is not None:
                    await port.post_card(asker["thread_key"], "info", "answer withdrawn",
                                         f'The answer to "{q["text"][:300]}" was withdrawn: the owner removed the fact it rested on. '
                                         "It is being routed again.", f"{routing.WITHDRAWN_PREFIX}{q['id']}")
            except Exception as exc:  # noqa: BLE001
                logger.warning("swarm_withdrawn_card_failed", question_id=q["id"], error_type=type(exc).__name__)
            await asyncio.to_thread(push.notify_thread, asker["thread_key"])
        await routing.advance(app_state, q["id"])
    await asyncio.to_thread(push.notify_roster)
    logger.info("swarm_fact_killed_reopened", fact_id=fact_id, reopened=[q["id"] for q in reopened])
    return [q["id"] for q in reopened]


async def forget(view: Any, caller: AgentCaller, args: Dict[str, Any]) -> Dict[str, Any]:
    agent = await routing.caller_agent(view, caller)
    fact_id = args.get("fact_id")
    if not isinstance(fact_id, str) or not fact_id:
        raise facts.FactRefused("fact_id is required")
    try:
        await body.run_db(lambda c: facts.forgettable(c, agent, fact_id))
        reopened = await kill_fact(view.app.state, fact_id)
    except facts.FactNotFound:
        raise facts.FactRefused("no such fact") from None
    except _DB_ERRORS as exc:
        logger.warning("swarm_forget_failed", fact_id=fact_id, error_type=type(exc).__name__)
        raise facts.FactRefused("the fact could not be deleted; try again") from None
    logger.info("swarm_fact_forgotten", fact_id=fact_id, agent_id=agent["id"])
    return {"fact_id": fact_id, "state": "killed", "reopened_question_ids": reopened}
