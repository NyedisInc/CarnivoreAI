
from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Callable, Optional, Tuple

import structlog

from src.core.resource_push import notifier, topics

logger = structlog.get_logger()

NOTIFY_MIN_INTERVAL_SECONDS: float = 5.0

MAX_SESSIONS: int = 512

Signature = Tuple[Optional[str], Any, Any]


def _publish(session_id: str) -> None:
    notifier.notify_coalesced(
        topics.SESSION_USAGE, session_id, NOTIFY_MIN_INTERVAL_SECONDS,
        detail=topics.keyed(topics.SESSION_USAGE, session_id),
    )


class SessionUsageWatch:

    def __init__(self, publish: Callable[[str], None] = _publish) -> None:
        self._publish = publish
        self._lock = threading.Lock()
        self._last: "OrderedDict[str, Signature]" = OrderedDict()

    def observe(self, session_id: str, evidence: Any) -> bool:
        facts = evidence.transcript
        if facts.newest_append_at is None and facts.turn_end_at is None:
            return False
        uuid = evidence.identity.conversation_uuid if evidence.identity is not None else None
        signature: Signature = (uuid, facts.newest_append_at, facts.turn_end_at)
        with self._lock:
            previous = self._last.get(session_id)
            self._last[session_id] = signature
            self._last.move_to_end(session_id)
            while len(self._last) > MAX_SESSIONS:
                self._last.popitem(last=False)
        if previous is None or previous == signature:
            return False
        self._publish(session_id)
        logger.debug("session_usage_changed", session_id=session_id)
        return True
