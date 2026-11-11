
from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional

import structlog

from src.core import db
from src.core.notifications import contracts, engine as engine_mod
from src.core.notifications.sources import common
from src.core.swarm import author_path, body, mac_toast, thread_port

logger = structlog.get_logger()

TYPE_ID = "swarm.question_climbed"


async def _card_hint(question_id: int) -> Dict[str, str]:
    try:
        card = await body.run_db(lambda c: author_path.question_card(c, question_id))
    except (sqlite3.Error, db.DatastoreUnreadableError, OSError) as exc:
        logger.info("swarm_question_card_hint_unread", question_id=question_id, error_type=type(exc).__name__)
        return {}
    if card is None:
        return {}
    crumbs = (card["askers"][0]["author_path"] if card["askers"] else []) or []
    return {k: v for k, v in (("ask", card["details"]), ("asker_path", "/".join(str(c.get("name") or "") for c in crumbs))) if v}


async def _first_asker(question_id: int) -> Optional[Dict[str, Any]]:
    def read(conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
        row = conn.execute("SELECT a.* FROM swarm_question_askers k JOIN swarm_agents a ON a.id = k.agent_id WHERE k.question_id = ? "
                           "AND a.torn_down_at IS NULL ORDER BY k.asked_at, k.agent_id LIMIT 1", (question_id,)).fetchone()
        return dict(row) if row is not None else None
    try:
        return await body.run_db(read)
    except (sqlite3.Error, db.DatastoreUnreadableError, OSError) as exc:
        logger.info("swarm_question_asker_unread", question_id=question_id, error_type=type(exc).__name__)
        return None


async def question_climbed(app_state: Any, item_id: int, question_id: int, text: str) -> bool:
    engine = engine_mod.current_engine()
    event = contracts.NotifyEvent(
        type_id=TYPE_ID, kind="swarm", title=common.type_title(TYPE_ID), ts=common.now(),
        severity=contracts.SEVERITY_WARN, instance_key=f"question:{question_id}", details=text, open_item=True,
        card_hint={**await _card_hint(question_id), "item": str(item_id)})
    queued = await engine.deliver(event) if engine is not None else False
    await mac_toast.record(app_state, await _first_asker(question_id), event)
    if engine is None:
        logger.info("swarm_question_climbed_no_engine", question_id=question_id)
        return False
    if not queued:
        logger.info("swarm_question_climbed_not_queued", question_id=question_id, item_id=item_id)
        return False
    logger.info("swarm_question_climbed", question_id=question_id, item_id=item_id)
    port = thread_port.get()
    if port is not None:
        try:
            await port.mark_phone_sent(item_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("swarm_phone_mark_failed", item_id=item_id, error_type=type(exc).__name__)
    return True
