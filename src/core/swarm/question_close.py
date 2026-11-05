
from __future__ import annotations

import asyncio
import re
import sqlite3
from typing import Any, Dict, List, Optional

import structlog

from src.core import db
from src.core.db import transaction
from src.core.mcp.caller import AgentCaller
from src.core.swarm import body, push, routing, thread_port
from src.core.swarm.routing import QuestionRefused
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

CLOSABLE = ("routing", "open", "reopened")
WITHDRAWN_BY, SKIPPED_BY = "withdrawn", "owner_skip"
SKIP_DECISION = "skip"
NOT_YOURS = "that question is not one of your open questions"
_DB_ERRORS = (sqlite3.Error, db.DatastoreUnreadableError, OSError)

_ITEM = re.compile(r"^\s*(?:[-*•]\s+)?(?:\*\*|__)?\(?(?:\d{1,2}|[A-Za-z])[.)]\s+\S", re.MULTILINE)
LIST_REFUSAL = (
    "swarm_ask refused: the question holds {n} numbered or lettered items. Send them as ONE swarm_ask with a typed `questions` "
    "batch, each item {{id (a-z0-9_-), type: yes_no | single | multi | rank | short_text | long_text, prompt, options "
    "[{{id, label, recommended, reason}}] for a choice or rank, recommend {{value | order | text, reason}} otherwise}}, and keep "
    "`question` as the shared context. swarm_ask takes `questions` even when your copy of its schema does not list it: a Claude "
    "Code conversation keeps the tool definitions it started with across restarts until a compaction.")


def list_items(text: str) -> int:
    return len(_ITEM.findall(text or ""))


def list_refusal(text: str) -> Optional[str]:
    n = list_items(text)
    return LIST_REFUSAL.format(n=n) if n >= 2 else None


def question_id_arg(value: Any, key: str = "question_id") -> int:
    if type(value) is not int or value < 1:
        raise QuestionRefused(f"{key} must be a positive whole number")
    return value


def _close_row(conn: sqlite3.Connection, question_id: int, by: str) -> Optional[str]:
    row = conn.execute("SELECT card_ref FROM swarm_questions WHERE id = ? AND state IN (?, ?, ?)", (question_id, *CLOSABLE)).fetchone()
    if row is None:
        return None
    conn.execute("UPDATE swarm_questions SET state = 'closed', answered_by = ?, answered_at = ? WHERE id = ?", (by, utc_now(), question_id))
    return row["card_ref"] or ""


def withdraw_rows(conn: sqlite3.Connection, agent_id: int, question_id: int) -> Dict[str, Any]:
    q = conn.execute("SELECT state FROM swarm_questions WHERE id = ?", (question_id,)).fetchone()
    mine = conn.execute("SELECT 1 FROM swarm_question_askers WHERE question_id = ? AND agent_id = ?", (question_id, agent_id)).fetchone()
    if q is None or mine is None or q["state"] not in CLOSABLE:
        raise QuestionRefused(NOT_YOURS)
    others = conn.execute("SELECT COUNT(*) FROM swarm_question_askers WHERE question_id = ? AND agent_id != ?",
                          (question_id, agent_id)).fetchone()[0]
    if others:
        conn.execute("DELETE FROM swarm_question_askers WHERE question_id = ? AND agent_id = ?", (question_id, agent_id))
        return {"question_id": question_id, "closed": False, "card_ref": None}
    return {"question_id": question_id, "closed": True, "card_ref": _close_row(conn, question_id, WITHDRAWN_BY)}


async def close_card(card_ref: Optional[str], question_id: int) -> None:
    port = thread_port.get()
    if port is None or not (card_ref or "").isdigit():
        return
    try:
        await port.close_card(int(card_ref), "closed")
    except Exception as exc:  # noqa: BLE001
        logger.warning("swarm_question_card_not_closed", question_id=question_id, error_type=type(exc).__name__)


async def withdraw(view: Any, caller: AgentCaller, args: Dict[str, Any]) -> Dict[str, Any]:
    agent = await routing.caller_agent(view, caller)
    qid = question_id_arg(args.get("question_id"))

    def run(conn: sqlite3.Connection) -> Dict[str, Any]:
        with transaction(conn):
            return withdraw_rows(conn, agent["id"], qid)

    try:
        done = await body.run_db(run)
    except _DB_ERRORS as exc:
        logger.warning("swarm_withdraw_failed", agent_id=agent["id"], error_type=type(exc).__name__)
        raise QuestionRefused("the question could not be withdrawn; try again") from None
    if done["closed"]:
        await close_card(done["card_ref"], qid)
    await asyncio.to_thread(push.notify_agent, agent["id"])
    logger.info("swarm_question_withdrawn", question_id=qid, agent_id=agent["id"], closed=done["closed"])
    return {"question_id": qid, "closed": done["closed"]}


def _skip_rows(conn: sqlite3.Connection, question_id: int) -> Dict[str, Any]:
    with transaction(conn):
        card = _close_row(conn, question_id, SKIPPED_BY)
        if card is None:
            raise QuestionRefused("that question is not waiting any more")
        return {"card_ref": card, "askers": routing.askers_of(conn, question_id)}


def skip_text(question_id: int) -> str:
    return (f"The owner skipped your question {question_id}: it is closed and will not be answered. Go on without it; ask again "
            "only if something has changed, and never with the same words.")


async def owner_skip(app_state: Any, question_id: int) -> List[int]:
    done = await body.run_db(lambda c: _skip_rows(c, question_id))
    await close_card(done["card_ref"], question_id)
    for asker in done["askers"]:
        await routing.tell(app_state, asker["id"], skip_text(question_id), source="swarm_answer", authority="data",
                           ref=f"{routing.QUESTION_PREFIX}{question_id}", reason="question")
        await asyncio.to_thread(push.notify_agent, asker["id"])
    logger.info("swarm_question_skipped", question_id=question_id, askers=len(done["askers"]))
    return [a["id"] for a in done["askers"]]
