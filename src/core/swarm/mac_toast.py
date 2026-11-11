
from __future__ import annotations

from typing import Any, Dict, Optional

import structlog

from src.core.notifications import agent_message, contracts
from src.core.notifications.sources import toast as toast_source
from src.core.swarm import body

logger = structlog.get_logger()

TOAST_KIND = "Notification"


async def record(app_state: Any, agent: Optional[Dict[str, Any]], event: contracts.NotifyEvent) -> Optional[str]:
    manager = getattr(app_state, "session_manager", None)
    if agent is None or manager is None:
        return None
    try:
        info = await body.live_info(app_state, agent)
        if info is None:
            return None
        toast = manager.record_toast(info.session.id, TOAST_KIND, event.title, event.details, notify_type=event.type_id)
    except (ValueError, AttributeError, OSError) as exc:
        logger.info("swarm_mac_toast_skipped", type_id=event.type_id, error_type=type(exc).__name__)
        return None
    toast_source.remember_hint(toast.id, event.card_hint)
    await agent_message._broadcast(toast, app_state=app_state)
    return toast.id
