
from __future__ import annotations

import hashlib
import secrets
import threading
import time
from typing import Callable, Dict, Tuple

TOKEN_TTL_SECONDS = 5.0
MAX_LIVE_TOKENS = 64


class TokenRefused(Exception):

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class OwnerTokens:

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._live: Dict[str, Tuple[str, str, float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def mint(self, plugin_id: str, session_ref: str) -> str:
        token = secrets.token_urlsafe(24)
        now = self._clock()
        with self._lock:
            self._live = {d: v for d, v in self._live.items() if v[2] > now}
            if len(self._live) >= MAX_LIVE_TOKENS:
                del self._live[min(self._live, key=lambda d: self._live[d][2])]
            self._live[self._digest(token)] = (plugin_id, session_ref, now + TOKEN_TTL_SECONDS)
        return token

    def redeem(self, plugin_id: str, token: object, session_ref: str) -> None:
        if not isinstance(token, str) or not token:
            raise TokenRefused("missing")
        with self._lock:
            entry = self._live.pop(self._digest(token), None)
        if entry is None:
            raise TokenRefused("unknown")
        owner, ref, expires = entry
        if expires <= self._clock():
            raise TokenRefused("expired")
        if owner != plugin_id or ref != session_ref:
            raise TokenRefused("wrong_session")
