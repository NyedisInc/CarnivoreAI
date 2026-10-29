
from __future__ import annotations

from typing import Callable, List, Optional

import structlog

logger = structlog.get_logger()

Listener = Callable[[str, Optional[str]], None]

_listeners: List[Listener] = []


def subscribe(listener: Listener) -> Callable[[], None]:
    _listeners.append(listener)

    def unsubscribe() -> None:
        if listener in _listeners:
            _listeners.remove(listener)

    return unsubscribe


def publish_append(session_id: str, tmux_name: Optional[str] = None) -> None:
    for listener in list(_listeners):
        try:
            listener(session_id, tmux_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("cplug_transcript_listener_failed", session_id=session_id, error=str(exc),
                           error_type=type(exc).__name__)


def listening() -> bool:
    return bool(_listeners)


def reset() -> None:
    _listeners.clear()
