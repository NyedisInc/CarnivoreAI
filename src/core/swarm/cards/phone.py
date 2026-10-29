
from __future__ import annotations

from typing import Any

import structlog

from src.core.notifications import contracts, engine as engine_mod
from src.core.notifications.sources import common
from src.core.swarm import thread_port

logger = structlog.get_logger()

TYPE_ID = "swarm.question_climbed"


async def question_climbed(app_state: Any, item_id: int, question_id: int, text: str) -> bool:
    engine = engine_mod.current_engine()
    if engine is None:
        logger.info("swarm_question_climbed_no_engine", question_id=question_id)
        return False
    event = contracts.NotifyEvent(
        type_id=TYPE_ID, kind="swarm", title=common.type_title(TYPE_ID), ts=common.now(),
        severity=contracts.SEVERITY_WARN, instance_key=f"question:{question_id}", details=text, open_item=True)
    if not await engine.deliver(event):
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
