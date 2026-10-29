
from __future__ import annotations

import asyncio
import sqlite3
from typing import Any, Dict, Mapping, Optional

import structlog

from src.core import db
from src.core.swarm import body, delivery, store, switch
from src.core.swarm.cards import capacity
from src.core.swarm.profiles import effective_profile

logger = structlog.get_logger()

SOURCE = "huddle_tell"
_ERRORS = (body.BodyError, sqlite3.Error, db.DatastoreUnreadableError, OSError, RuntimeError)


async def tell(app_state: Any, agent_id: int, text: str, *, ref: str, authority: str = "data",
               owner_message_ref: Optional[str] = None, wake: bool = True) -> str:
    if not switch.is_on():
        return f"refused:{switch.CODE}"
    try:
        outcome = await delivery.deliver_text(app_state, agent_id, text, source=SOURCE, authority=authority, source_ref=ref,
                                              owner_message_ref=owner_message_ref)
        if outcome == "refused:asleep" and wake:
            await body.wake(app_state, agent_id, "crosstalk", authority, orders=text, owner_message_ref=owner_message_ref)
            return "woke"
        return outcome
    except _ERRORS as exc:
        logger.warning("swarm_card_tell_failed", agent_id=agent_id, ref=ref, error_type=type(exc).__name__)
        return "refused:error"


async def interrupt(app_state: Any, agent_id: int, *, ref: str = "card_pause") -> bool:
    if not switch.is_on():
        return False
    try:
        agent = await body.run_db(lambda c: store.get_agent(c, agent_id))
        info = await body.live_info(app_state, agent) if agent else None
        if info is None:
            return False
        await asyncio.to_thread(delivery.record_for_session_row, info.session_row_id, "send_keys", ref)
        await app_state.session_manager.send_input("\x1b", session_id=info.session.id)
        return True
    except _ERRORS as exc:
        logger.warning("swarm_card_interrupt_failed", agent_id=agent_id, error_type=type(exc).__name__)
        return False


def slot_refusal(conn: sqlite3.Connection, agent: Dict[str, Any], project_id: Optional[int] = None,
                 grants: Optional[Mapping[str, int]] = None) -> Optional[str]:
    if agent.get("state") != "asleep":
        return None
    caps = body.caps_refusal(conn, agent, machine=False)
    if caps:
        return caps
    profile = effective_profile(agent)
    code = capacity.refusal(conn, project_id, grants or {}, floors=False, profile=profile)
    return capacity.refusal_text(code, profile) if code else None
