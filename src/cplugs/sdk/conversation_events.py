
from __future__ import annotations

from typing import Callable, List

import structlog

logger = structlog.get_logger()

Listener = Callable[[str], None]

_listeners: List[Listener] = []


def subscribe(listener: Listener) -> Callable[[], None]:
    _listeners.append(listener)

    def unsubscribe() -> None:
        if listener in _listeners:
            _listeners.remove(listener)

    return unsubscribe


def publish_changed(session_key: str) -> None:
    for listener in list(_listeners):
        try:
            listener(session_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("cplug_conversation_listener_failed", session_key=session_key, error=str(exc), error_type=type(exc).__name__)


def reset() -> None:
    _listeners.clear()
