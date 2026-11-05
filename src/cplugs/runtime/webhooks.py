
from __future__ import annotations

import hashlib
import heapq
import hmac
import time
from collections import deque
from typing import Callable, Deque, Dict, List, Mapping, Optional, Tuple

MAX_BODY_BYTES = 256 * 1024
MAX_SKEW_SECONDS = 300
MAX_FUTURE_SECONDS = 30
PER_HOOK_PER_MINUTE = 60
NONCE_LIFETIME_MINUTES = -(-(MAX_SKEW_SECONDS + MAX_FUTURE_SECONDS) // 60)
NONCE_CACHE_HOOKS = 8
HOOK_NONCE_QUOTA = PER_HOOK_PER_MINUTE * NONCE_LIFETIME_MINUTES
NONCE_CACHE_SIZE = HOOK_NONCE_QUOTA * NONCE_CACHE_HOOKS
MIN_SECRET_BYTES = 16


class WebhookRefused(Exception):

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def sign(secret: bytes, timestamp: int, nonce: str, body: bytes) -> str:
    return hmac.new(secret, b"%d.%s." % (timestamp, nonce.encode("utf-8")) + body, hashlib.sha256).hexdigest()


def _before_start(ts: int, started: int) -> bool:
    return ts < started + MAX_FUTURE_SECONDS


class InboundVerifier:

    def __init__(self, clock: Callable[[], float] = time.time, *, started_at: Optional[float] = None) -> None:
        self._clock = clock
        self._started = int(clock() if started_at is None else started_at)
        self._nonces: Dict[str, int] = {}
        self._expiries: List[Tuple[int, str, str]] = []
        self._live: Dict[str, int] = {}
        self._forgot = float("-inf")
        self._hits: Dict[str, Deque[float]] = {}

    def _count_against_window(self, hook: str, now: float) -> None:
        window = self._hits.setdefault(hook, deque())
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= PER_HOOK_PER_MINUTE:
            raise WebhookRefused("rate_limited")
        window.append(now)

    def _purge(self, now: float) -> None:
        while self._expiries and self._expiries[0][0] < now:
            expiry, hook, key = heapq.heappop(self._expiries)
            self._forgot = max(self._forgot, expiry)
            self._nonces.pop(key, None)
            self._live[hook] -= 1
            if not self._live[hook]:
                del self._live[hook]

    def _check_room(self, hook: str) -> None:
        if self._live.get(hook, 0) >= HOOK_NONCE_QUOTA or len(self._nonces) >= NONCE_CACHE_SIZE:
            raise WebhookRefused("cache_full")

    def verify(self, hook: str, secret: bytes, headers: Mapping[str, str], body: bytes) -> bytes:
        if len(body) > MAX_BODY_BYTES:
            raise WebhookRefused("too_large")
        if not isinstance(secret, (bytes, bytearray)) or len(secret) < MIN_SECRET_BYTES:
            raise WebhookRefused("bad_signature")
        now = self._clock()
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
        if now - ts > MAX_SKEW_SECONDS or ts - now > MAX_FUTURE_SECONDS:
            raise WebhookRefused("stale")
        if _before_start(ts, self._started):
            raise WebhookRefused("before_start")
        if ts + MAX_SKEW_SECONDS <= self._forgot:
            raise WebhookRefused("stale")
        self._purge(now)
        key = f"{hook}:{nonce}"
        if key in self._nonces:
            raise WebhookRefused("replay")
        self._check_room(hook)
        self._count_against_window(hook, now)
        expiry = ts + MAX_SKEW_SECONDS
        self._nonces[key] = expiry
        heapq.heappush(self._expiries, (expiry, hook, key))
        self._live[hook] = self._live.get(hook, 0) + 1
        return body
