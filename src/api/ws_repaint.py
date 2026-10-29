
from __future__ import annotations

import asyncio
import base64
from typing import Any, Optional

import structlog

from src.api.ws_connections import _resolve_backend
from src.api.ws_startup_paint import _CLEAR_AND_HOME
from src.core import viewer_fanout
from src.core.bounded_stream import OFFER_ACCEPTED

logger = structlog.get_logger()


async def capture_screen(websocket: Any, session_id: Optional[str]) -> tuple[Optional[bytes], str]:
    services = getattr(websocket.app.state, "services", None)
    registry = getattr(services, "registry", None)
    backend = _resolve_backend(registry, session_id) if registry is not None else None
    if backend is None:
        logger.info("ws_repaint_no_backend", session_id=session_id)
        return None, "no_backend"
    try:
        screen = await asyncio.to_thread(backend.capture_visible_screen)
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("ws_repaint_capture_failed", session_id=session_id, error=str(exc))
        return None, "capture_failed"
    if not screen:
        return None, "nothing"
    return screen, "ok"


async def repaint(websocket: Any, session_id: Optional[str], stream: Any) -> str:
    if not viewer_fanout.is_viewer_stream(stream):
        return "no_stream"
    screen, why = await capture_screen(websocket, session_id)
    if screen is None:
        return why
    outcome = viewer_fanout.offer_paint(
        stream, base64.b64encode(_CLEAR_AND_HOME + screen).decode("ascii"))
    logger.debug("ws_repaint", session_id=session_id, size=len(screen), outcome=outcome)
    return "queued" if outcome == OFFER_ACCEPTED else outcome
