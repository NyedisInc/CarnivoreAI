
from __future__ import annotations

from typing import Any, Literal, Mapping, Optional

import structlog
from pydantic import BaseModel, Field

from src.core.mcp import channel as channel_events
from src.core.session_delivery import cold_start, delivery_confirm
from src.core.sessions import guarded_paste
from src.core.sessions.guarded_paste import GateOptions

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
    confirmation: Optional[str] = Field(None, exclude=True, description="A cold-started session's channel push: delivered | resent | unconfirmed (#3014); None when not checked")


def _channel_pane(app_state: Any, session_id: str) -> Optional[str]:
    if not channel_events.REGISTRY.count() or not channel_events.channels_enabled():
        return None
    session = app_state.services.registry.get_session(session_id)
    tmux_name = session.tmux_session if session is not None else None
    return tmux_name if channel_events.REGISTRY.is_open(tmux_name) else None


async def deliver_through_gates(app_state: Any, session_id: str, text: str,
                                meta: Optional[Mapping[str, str]] = None, *,
                                fresh_dialog_check: bool = False) -> DeliveryResponse:
    options = GateOptions(fresh_dialog_check=fresh_dialog_check)
    tmux_name = _channel_pane(app_state, session_id)
    if tmux_name is None:
        pasted = await guarded_paste.paste_through_gates(app_state, session_id, text, options)
        return DeliveryResponse(pasted_bytes=pasted.pasted_bytes, submitted=pasted.submitted, delivered_via=VIA_PASTE)
    gated = await guarded_paste.check_through_gates(app_state, session_id, text, options)
    if cold_start.is_cold(session_id):
        confirmation = await delivery_confirm.push_confirmed(app_state, session_id, tmux_name, gated.clean.text, meta or {})
        if confirmation is not None:
            return DeliveryResponse(pasted_bytes=gated.clean.byte_length, submitted=True, delivered_via=VIA_CHANNEL,
                                    confirmation=confirmation)
    elif channel_events.REGISTRY.push(tmux_name, gated.clean.text, meta or {}):
        logger.info("channel_delivery_sent", session_id=session_id, tmux_session=tmux_name,
                    bytes=gated.clean.byte_length, activity_status=gated.activity_status)
        return DeliveryResponse(pasted_bytes=gated.clean.byte_length, submitted=True, delivered_via=VIA_CHANNEL)
    logger.info("channel_delivery_fell_back", session_id=session_id, tmux_session=tmux_name)
    pasted = await guarded_paste.paste_gated(gated, session_id)
    return DeliveryResponse(pasted_bytes=pasted.pasted_bytes, submitted=pasted.submitted, delivered_via=VIA_PASTE)
