
from __future__ import annotations

from typing import Callable, List, Optional

import structlog

logger = structlog.get_logger()

Listener = Callable[[Optional[str]], None]

_listeners: List[Listener] = []


def subscribe(listener: Listener) -> Callable[[], None]:
    _listeners.append(listener)

    def unsubscribe() -> None:
        if listener in _listeners:
            _listeners.remove(listener)

    return unsubscribe


def publish_turn_end(session_id: Optional[str] = None) -> None:
    """Tell every listener a session's turn ended or the session is gone. Never raises.

    Inputs: session_id - the session's ``ses_`` id, or None when not known. Output: None.
    A listener's failure is logged with its type and the next listener still runs (the caller is the watcher's tick,
    which no plugin may cost).
    """
    for listener in list(_listeners):
        try:
            listener(session_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("cplug_turn_listener_failed", session_id=session_id, error=str(exc),
                           error_type=type(exc).__name__)


def reset() -> None:
    _listeners.clear()
