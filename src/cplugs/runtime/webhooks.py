
from __future__ import annotations

import hashlib
import hmac
import time
from collections import deque
from typing import Callable, Deque, Dict, Mapping

MAX_BODY_BYTES = 256 * 1024
MAX_SKEW_SECONDS = 300
NONCE_CACHE_SIZE = 2048
PER_HOOK_PER_MINUTE = 60
MIN_SECRET_BYTES = 16


class WebhookRefused(Exception):

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def sign(secret: bytes, timestamp: int, nonce: str, body: bytes) -> str:
    return hmac.new(secret, b"%d.%s." % (timestamp, nonce.encode("utf-8")) + body, hashlib.sha256).hexdigest()


class InboundVerifier:

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._nonces: Dict[str, float] = {}
        self._order: Deque[str] = deque()
        self._hits: Dict[str, Deque[float]] = {}

    def verify(self, hook: str, secret: bytes, headers: Mapping[str, str], body: bytes) -> bytes:
        if len(body) > MAX_BODY_BYTES:
            raise WebhookRefused("too_large")
        if not isinstance(secret, (bytes, bytearray)) or len(secret) < MIN_SECRET_BYTES:
            raise WebhookRefused("bad_signature")
        now = self._clock()
        window = self._hits.setdefault(hook, deque())
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= PER_HOOK_PER_MINUTE:
            raise WebhookRefused("rate_limited")
        window.append(now)
        try:
            ts, nonce, given = int(headers.get("x-timestamp", "")), headers.get("x-nonce", ""), headers.get("x-signature", "")
        except ValueError as exc:
            raise WebhookRefused("bad_signature") from exc
        try:
            matches = hmac.compare_digest(sign(secret, ts, nonce, body).encode("ascii"), given.encode("ascii", "strict"))
        except UnicodeEncodeError as exc:
            raise WebhookRefused("bad_signature") from exc
        if not nonce or len(nonce) > 64 or not matches:
            raise WebhookRefused("bad_signature")
        if abs(now - ts) > MAX_SKEW_SECONDS:
            raise WebhookRefused("stale")
        key = f"{hook}:{nonce}"
        if key in self._nonces:
            raise WebhookRefused("replay")
        self._nonces[key] = now
        self._order.append(key)
        while len(self._order) > NONCE_CACHE_SIZE:
            self._nonces.pop(self._order.popleft(), None)
        return body
