
from __future__ import annotations

import asyncio
import sqlite3
from typing import Any, Dict, List

import structlog

from src.core import db
from src.core.mcp.caller import AgentCaller
from src.core.swarm import body, push, spawn, thread_port

logger = structlog.get_logger()

MAX_SAY_CHARS = 4000
THREAD_LINE = ("The owner reads only your thread, and your final answer of every turn the owner started is posted there for you, "
               "word for word: answer the owner in your normal reply. Use swarm_say only to tell the owner something between "
               "turns, never to answer an owner message.")
HELD_DETAIL = ("held: your final answer of this turn is posted to the owner's thread when the turn ends, so this text is "
               "posted only if that answer is empty; swarm_say is for posts between turns")


class SayRefused(ValueError):
    pass


def _text(args: Dict[str, Any]) -> str:
    from src.core.mcp.tools import redact_text

    text = args.get("text")
    if not isinstance(text, str) or not text.strip():
        raise SayRefused("text is required")
    text = text.strip()
    if len(text) > MAX_SAY_CHARS:
        raise SayRefused(f"the reply must be at most {MAX_SAY_CHARS} characters")
    return redact_text(text)


async def post_as_agent(agent: Dict[str, Any], text: str) -> str:
    port = thread_port.get()
    if port is None:
        raise SayRefused("the huddle plugin is off, so there is no thread to answer in")

    def durable_key(conn: sqlite3.Connection) -> str:
        found = conn.execute("SELECT session_uuid FROM sessions WHERE id = ?", (agent["session_row_id"],)).fetchone()
        return str(found[0]) if found and found[0] else agent["thread_key"]

    try:
        key = await body.run_db(durable_key)
    except (sqlite3.Error, db.DatastoreUnreadableError):
        raise SayRefused("the reply could not be saved; try again") from None
    parts = chunks(clean_text(text), MAX_SAY_CHARS)
    if not parts:
        raise SayRefused("text is required")
    refs = [await port.post_agent_message(agent["thread_key"], part, key) for part in parts]
    await asyncio.to_thread(push.notify_thread, agent["thread_key"])
    await asyncio.to_thread(push.notify_agent, agent["id"])
    return refs[0]


def clean_text(text: str) -> str:
    from src.core.mcp.tools import redact_text

    return "".join(c for c in redact_text(text).replace("\r\n", "\n").replace("\r", "\n") if c in "\n\t" or ord(c) >= 32).strip()


def chunks(text: str, limit: int) -> List[str]:
    out: List[str] = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit + 1)
        cut = cut if cut > 0 else limit
        out.append(text[:cut].rstrip())
        text = text[cut:].lstrip("\n")
    out.append(text)
    return [part for part in out if part.strip()]


async def say(view: Any, caller: AgentCaller, args: Dict[str, Any]) -> Dict[str, Any]:
    from src.core.swarm import reply_mirror

    try:
        agent = await spawn.parent_agent(view, caller)
    except spawn.SpawnRefused as exc:
        raise SayRefused(str(exc)) from None
    text = _text(args)
    if thread_port.get() is None:
        raise SayRefused("the huddle plugin is off, so there is no thread to answer in")
    if await reply_mirror.hold_say(agent, text):
        return {"message_ref": None, "held": True, "detail": HELD_DETAIL}
    ref = await post_as_agent(agent, text)
    logger.info("swarm_said", agent_id=agent["id"], message_ref=ref)
    return {"message_ref": ref}
