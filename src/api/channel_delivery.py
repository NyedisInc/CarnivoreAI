
from __future__ import annotations

from typing import Literal, Mapping, Optional

import structlog
from fastapi import Request
from pydantic import BaseModel, Field

from src.api import one_shot_routes
from src.core.mcp import channel as channel_events

logger = structlog.get_logger()

VIA_CHANNEL = "channel"
VIA_PASTE = "paste"


class DeliveryResponse(BaseModel):
    """How one line went out.

    Fields: pasted_bytes (int) - the line's UTF-8 length after sanitising; submitted (bool) - True on success (for a
      channel push: queued for the wire, which is not proof Claude read it); delivered_via (``channel`` | ``paste``).
    """

    pasted_bytes: int = Field(..., description="Bytes delivered (pasted, or the channel event body)")
    submitted: bool = Field(..., description="True when the line went out")
    delivered_via: Literal["channel", "paste"] = Field(..., description="channel: a Claude Code channel event; paste: typed into the pane")


def _channel_pane(request: Request, session_id: str) -> Optional[str]:
    if not channel_events.REGISTRY.count() or not channel_events.channels_enabled():
        return None
    session = request.app.state.services.registry.get_session(session_id)
    tmux_name = session.tmux_session if session is not None else None
    return tmux_name if channel_events.REGISTRY.is_open(tmux_name) else None


async def deliver_through_gates(request: Request, session_id: str, text: str,
                                meta: Optional[Mapping[str, str]] = None, *,
                                fresh_dialog_check: bool = False) -> DeliveryResponse:
    extra = {"fresh_dialog_check": True} if fresh_dialog_check else {}
    tmux_name = _channel_pane(request, session_id)
    if tmux_name is None:
        pasted = await one_shot_routes.paste_through_gates(request, session_id, text, **extra)
        return DeliveryResponse(pasted_bytes=pasted.pasted_bytes, submitted=pasted.submitted, delivered_via=VIA_PASTE)
    gated = await one_shot_routes.check_through_gates(request, session_id, text, **extra)
    if channel_events.REGISTRY.push(tmux_name, gated.clean.text, meta or {}):
        logger.info("channel_delivery_sent", session_id=session_id, tmux_session=tmux_name,
                    bytes=gated.clean.byte_length, activity_status=gated.activity_status)
        return DeliveryResponse(pasted_bytes=gated.clean.byte_length, submitted=True, delivered_via=VIA_CHANNEL)
    logger.info("channel_delivery_fell_back", session_id=session_id, tmux_session=tmux_name)
    pasted = await one_shot_routes.paste_gated(gated, session_id)
    return DeliveryResponse(pasted_bytes=pasted.pasted_bytes, submitted=pasted.submitted, delivered_via=VIA_PASTE)
