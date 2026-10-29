
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional

import structlog

logger = structlog.get_logger()

MAX_PENDING_FLOWS = 8

DEFAULT_EXPIRES_IN = 900

MAILBOX_PATHS = {
    "google": ("/auth/google/mailbox/start", "/auth/google/mailbox/verify"),
    "github": ("/auth/github/mailbox/start", "/auth/github/mailbox/verify"),
}

_FLOW_ID_BYTES = 16


@dataclass(frozen=True)
class PendingEmailFlow:

    email: str
    session: str
    expires_at: float
    started_at: float
    ticket: str = ""
    provider: str = "google"


class EmailFlowStore:

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._flows: Dict[str, PendingEmailFlow] = {}

    def start(
        self, *, email: str, session: str, expires_in: int = DEFAULT_EXPIRES_IN,
        ticket: str = "", provider: str = "google",
    ) -> str:
        now = self._clock()
        self._prune(now)
        if len(self._flows) >= MAX_PENDING_FLOWS:
            oldest = min(self._flows, key=lambda key: self._flows[key].started_at)
            del self._flows[oldest]
            logger.info("catalog_email_flow_evicted")
        flow_id = secrets.token_urlsafe(_FLOW_ID_BYTES)
        self._flows[flow_id] = PendingEmailFlow(
            email=email,
            session=session,
            expires_at=now + max(int(expires_in or DEFAULT_EXPIRES_IN), 0),
            started_at=now,
            ticket=ticket,
            provider=provider,
        )
        logger.info("catalog_email_flow_started", pending=len(self._flows))
        return flow_id

    def pending_for(self, flow_id: str) -> Optional[PendingEmailFlow]:
        now = self._clock()
        self._prune(now)
        return self._flows.get(flow_id)

    def finish(self, flow_id: str) -> None:
        self._flows.pop(flow_id, None)

    def _prune(self, now: float) -> None:
        expired = [key for key, flow in self._flows.items() if flow.expires_at <= now]
        for key in expired:
            del self._flows[key]

