
from __future__ import annotations

import sqlite3
from typing import Any, Optional

import structlog

from src.core import db
from src.core.swarm import body, body_create, store

logger = structlog.get_logger()


async def adopt(app_state: Any, session_uuid: str, session_id: Optional[str], fresh: bool) -> Optional[int]:
    if not session_id:
        return None
    try:
        info = await app_state.session_manager.get_session_info(session_id)
        if info is None or info.session_row_id is None:
            return None
        row_id = int(info.session_row_id)
        agent = await body.run_db(lambda c: store.get_agent_by_session_row(c, row_id))
        if agent is None or agent["torn_down_at"] is not None or agent.get("host_key", "local") != "local":
            return None
        async with body.agent_lock(agent["id"]):
            wake_id = await body.run_db(lambda c: store.open_wake(c, agent["id"], reason="manual",
                                                                   mode="fresh" if fresh else "resume", authority="owner"))
    except (db.DatastoreUnreadableError, sqlite3.Error, RuntimeError) as exc:
        logger.warning("swarm_plain_wake_not_adopted", session_uuid=session_uuid, error=str(exc)[:200])
        return None
    if wake_id is None:
        return None
    ident = body_create.BodyIdentity(session_id, row_id, session_uuid, str(info.tmux_session), info.session.tmux_created_epoch)
    try:
        await body.finish_start(app_state, agent, wake_id, ident)
    except (body_create.CreateRefused, db.DatastoreUnreadableError, sqlite3.Error, OSError, RuntimeError) as exc:
        logger.warning("swarm_plain_wake_finish_failed", agent_id=agent["id"], error=str(exc)[:200])
        await body._unwind(agent["id"], wake_id)
        return None
    logger.info("swarm_plain_wake_adopted", agent_id=agent["id"], wake_id=wake_id, fresh=fresh)
    return wake_id
