
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, Mapping, Optional

import structlog

from src.models.websocket import WSMessageType

logger = structlog.get_logger()

GATE_FIELD = "crosstalk_cards"
PREVIEW_CHARS = 160
CARD_SOURCES_EXCLUDED = frozenset({"system"})

_publish: Optional[Callable[[Dict[str, Any]], int]] = None
_loop: Optional[asyncio.AbstractEventLoop] = None
_read_preferences: Optional[Callable[[], Mapping[str, Any]]] = None


def install(
    publish: Callable[[Dict[str, Any]], int], loop: asyncio.AbstractEventLoop, read_preferences: Callable[[], Mapping[str, Any]],
) -> None:
    global _publish, _loop, _read_preferences
    _publish, _loop, _read_preferences = publish, loop, read_preferences


def enabled() -> bool:
    if _read_preferences is None:
        return False
    return (_read_preferences().get("values") or {}).get(GATE_FIELD) is True


def uninstall() -> None:
    global _publish, _loop, _read_preferences
    _publish, _loop, _read_preferences = None, None, None


def frame_of(message: Mapping[str, Any]) -> Dict[str, Any]:
    from src.core.crosstalk.history import redact

    text = str(redact(str(message.get("text") or "")))
    preview = text if len(text) <= PREVIEW_CHARS else text[: PREVIEW_CHARS - 1] + "…"
    return {
        "type": WSMessageType.CROSSTALK_CARD.value,
        "id": message.get("id"),
        "thread": message.get("thread"),
        "sender_id": message.get("sender_id"),
        "sender_uuid": message.get("sender_uuid"),
        "sender_name": message.get("sender_name"),
        "sender_provider": message.get("sender_provider"),
        "sender_model": message.get("sender_model"),
        "receiver_id": message.get("receiver_id"),
        "receiver_uuid": message.get("receiver_uuid"),
        "receiver_name": message.get("receiver_name"),
        "receiver_provider": message.get("receiver_provider"),
        "receiver_model": message.get("receiver_model"),
        "preview": preview,
        "at": message.get("delivered_at") or time.time(),
    }


def announce(message: Mapping[str, Any]) -> None:
    publish, loop = _publish, _loop
    if publish is None or loop is None or message.get("source") in CARD_SOURCES_EXCLUDED:
        return
    try:
        if not enabled():
            return
        frame = frame_of(message)
        loop.call_soon_threadsafe(_send, publish, frame)
    except RuntimeError as exc:
        logger.debug("crosstalk_card_loop_closed", error=str(exc))
    except OSError as exc:
        logger.warning("crosstalk_card_gate_failed", error=str(exc), error_type=type(exc).__name__)


def _send(publish: Callable[[Dict[str, Any]], int], frame: Dict[str, Any]) -> None:
    try:
        publish(frame)
    except (RuntimeError, ValueError, TypeError) as exc:
        logger.warning("crosstalk_card_publish_failed", message_id=frame.get("id"), error=str(exc))
