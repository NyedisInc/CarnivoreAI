
from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional

import structlog

from src.core import db
from src.core.mcp.caller import AgentCaller
from src.core.swarm import spawn

logger = structlog.get_logger()

SWARM_AGENT = "swarm_agent"
PANE = "pane"

STANDING: Dict[str, str] = {
    **{name: SWARM_AGENT for name in (
        "swarm_report", "swarm_accept_report", "swarm_propose_naming", "swarm_suggest", "swarm_remember", "swarm_forget", "swarm_ask",
        "swarm_answer", "swarm_pass", "swarm_promote", "swarm_say", "swarm_conflict",
        "swarm_card_create", "swarm_card_start", "swarm_card_handoff", "swarm_card_finish", "swarm_card_close", "swarm_card_release",
        "swarm_card_reorder", "swarm_card_deal", "swarm_card_auto_promote", "swarm_card_queue", "swarm_card_verdict", "swarm_card_archive",
    )},
    "messaging_send": PANE,
}

_NOT_SWARM = "not_a_swarm_agent: {name} is a Swarm agent's own tool; only a Swarm agent's session may call it"
_NOT_PANE = "{name} runs only from a session on this computer, never from a token: it acts as that session"
_UNREADABLE = "{name} refused: the Swarm datastore could not be read to check the caller"


async def refusal(manager: Any, caller: AgentCaller, name: str) -> Optional[str]:
    standing = STANDING.get(name)
    if standing is None:
        return None
    if caller.from_token:
        return (_NOT_SWARM if standing == SWARM_AGENT else _NOT_PANE).format(name=name)
    if standing == PANE:
        return None
    try:
        await spawn.parent_agent(manager, caller)
    except spawn.SpawnRefused:
        return _NOT_SWARM.format(name=name)
    except (db.DatastoreUnreadableError, sqlite3.Error) as exc:
        logger.warning("mcp_pane_only_check_failed", tool=name, error_type=type(exc).__name__)
        return _UNREADABLE.format(name=name)
    return None
