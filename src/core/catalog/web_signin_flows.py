
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional

FLOW_TTL_SECONDS = 600
MAX_FLOWS = 8


@dataclass(frozen=True)
class WebFlow:

    verifier: str
    provider: str
    expires_at: float
    started_at: float


def new_verifier() -> str:
    return secrets.token_urlsafe(32)


def challenge_of(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode().rstrip("=")


class WebFlowStore:

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._flows: Dict[str, WebFlow] = {}

    def start(self, flow_id: str, verifier: str, provider: str, expires_in: int) -> None:
        now = self._clock()
        self._prune(now)
        if len(self._flows) >= MAX_FLOWS:
            del self._flows[min(self._flows, key=lambda key: self._flows[key].started_at)]
        ttl = min(max(int(expires_in), 0), FLOW_TTL_SECONDS)
        self._flows[flow_id] = WebFlow(verifier, provider, now + ttl, now)

    def get(self, flow_id: str) -> Optional[WebFlow]:
        self._prune(self._clock())
        return self._flows.get(flow_id)

    def finish(self, flow_id: str) -> None:
        self._flows.pop(flow_id, None)

    def _prune(self, now: float) -> None:
        for key in [k for k, flow in self._flows.items() if flow.expires_at <= now]:
            del self._flows[key]
