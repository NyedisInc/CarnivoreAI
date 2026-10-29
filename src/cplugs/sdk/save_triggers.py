
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import structlog

logger = structlog.get_logger()

NOT_LIFECYCLE = frozenset({"live", "plugins", "summarize", "backfill", "rechunk"})


@dataclass(frozen=True)
class LifecycleSave:

    event: str
    conversation_id: str
    session_uuid: Optional[str] = None
    family: str = "claude"
    facts: Dict[str, Any] = field(default_factory=dict)


Listener = Callable[[LifecycleSave], None]
_listeners: List[Listener] = []


def subscribe(listener: Listener) -> Callable[[], None]:
    _listeners.append(listener)
    return lambda: _listeners.remove(listener) if listener in _listeners else None


def is_lifecycle(event: str) -> bool:
    return event not in NOT_LIFECYCLE


def announce(save: LifecycleSave) -> int:
    ran = 0
    for listener in list(_listeners):
        try:
            listener(save)
            ran += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("save_trigger_listener_failed", save_event=save.event, conversation_id=save.conversation_id,
                         error_type=type(exc).__name__, error=str(exc)[:300])
    return ran


__all__ = ["LifecycleSave", "announce", "is_lifecycle", "subscribe"]
