
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

import structlog

from src.core import session_change_notice
from src.core.subagents import shape_alert
from src.models.websocket import WSMessageType

logger = structlog.get_logger(__name__)


def build_frame(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": WSMessageType.DEV_SHAPE_UNRECOGNIZED,
        "file_kind": str(payload.get("file_kind", "")),
        "contract_version": payload.get("contract_version"),
        "problems": [str(problem) for problem in payload.get("problems", ())],
    }


def install(app_state: Any, loop: Optional[asyncio.AbstractEventLoop], *,
            enabled: bool) -> bool:
    if not enabled or loop is None:
        shape_alert.set_listener(None)
        return False

    def _listener(payload: Dict[str, Any]) -> None:
        loop.call_soon_threadsafe(
            session_change_notice.publish, app_state, build_frame(payload)
        )

    shape_alert.set_listener(_listener)
    logger.info("dev_shape_alerts_enabled")
    return True
