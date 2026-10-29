
from __future__ import annotations

import time
import unicodedata
from collections import deque
from typing import Any, Callable, Deque, Dict, Optional

import structlog

from src.config import settings
from src.core.notifications.copy import defang_urls
from src.core.timers.redact import redact

logger = structlog.get_logger()

MAX_CHARS: int = 280
TOAST_KIND: str = "Notification"
TOAST_TITLE: str = "agent message"
SESSION_WINDOWS = ((60.0, 3), (600.0, 5))
GLOBAL_WINDOW = (3600.0, 30)


class AgentNotifyError(Exception):

    def __init__(self, status: int, message: str, retry_after: Optional[int] = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.retry_after = retry_after


class Limiter:

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._sessions: Dict[str, Deque[float]] = {}
        self._global: Deque[float] = deque()

    @staticmethod
    def _trim(stamps: Deque[float], now: float, horizon: float) -> None:
        while stamps and now - stamps[0] >= horizon:
            stamps.popleft()

    @staticmethod
    def _wait(stamps: Deque[float], now: float, window: float, limit: int) -> float:
        recent = [s for s in stamps if now - s < window]
        if len(recent) < limit:
            return 0.0
        return window - (now - recent[len(recent) - limit])

    def check(self, session_id: str) -> None:
        now = self._clock()
        mine = self._sessions.setdefault(session_id, deque())
        self._trim(mine, now, SESSION_WINDOWS[-1][0])
        self._trim(self._global, now, GLOBAL_WINDOW[0])
        waits = [self._wait(mine, now, w, n) for w, n in SESSION_WINDOWS]
        waits.append(self._wait(self._global, now, *GLOBAL_WINDOW))
        worst = max(waits)
        if worst > 0:
            raise AgentNotifyError(429, "too many agent notifications; try again later", retry_after=int(worst) + 1)
        mine.append(now)
        self._global.append(now)
        if len(self._sessions) > 512:
            for key in [k for k, v in self._sessions.items() if not v]:
                del self._sessions[key]


_LIMITER = Limiter()


def enabled() -> bool:
    try:
        return bool(settings.load_auth_config().mcp.agent_notify)
    except (ValueError, OSError):
        return False


def clean_text(text: Any) -> str:
    if not isinstance(text, str):
        raise AgentNotifyError(422, "text must be a string")
    kept = "".join(" " if ch in "\n\r\t" else ch for ch in text if ch in "\n\r\t" or unicodedata.category(ch) != "Cc").strip()
    if not kept:
        raise AgentNotifyError(422, "text is empty")
    if len(kept) > MAX_CHARS:
        raise AgentNotifyError(422, f"text is {len(kept)} characters; the limit is {MAX_CHARS}. Shorten it and resend")
    return kept


async def send(session_manager: Any, session_id: str, text: Any, *, limiter: Optional[Limiter] = None) -> Dict[str, Any]:
    if not enabled():
        raise AgentNotifyError(403, "agent notify is off (mcp.agent_notify)")
    scrubbed = defang_urls(redact(clean_text(text)))
    (limiter or _LIMITER).check(session_id)
    try:
        toast = session_manager.record_toast(
            session_id=session_id, kind=TOAST_KIND, title=TOAST_TITLE, body=scrubbed, notify_type="agent.message")
    except ValueError as exc:
        raise AgentNotifyError(404, "that session is not live") from exc
    await _broadcast(toast)
    logger.info("agent_notify_sent", session_id=session_id, length=len(scrubbed))
    return {"sent": True, "toast_id": toast.id}


async def _broadcast(toast: Any) -> None:
    from src.api.websocket import connection_manager
    from src.models import ToastNewMessage

    try:
        await connection_manager.broadcast_to_session(toast.session_id, ToastNewMessage(toast=toast).model_dump_json())
    except (OSError, RuntimeError) as exc:
        logger.warning("agent_notify_broadcast_failed", session_id=toast.session_id, error=type(exc).__name__)
