from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

WINDOW_S: float = 600.0
MAX_KEYS: int = 256
UA_MAX: int = 120


@dataclass
class _Entry:
    last_logged: float
    folded: int = 0


@dataclass(frozen=True)
class Verdict:

    known: bool
    log: bool
    repeats: int


def _key(token: str, client: Optional[str]) -> str:
    return hashlib.sha256(f"{token}\0{client or ''}".encode("utf-8")).hexdigest()[:24]


class DeadTokenLog:

    def __init__(self, *, window_s: float = WINDOW_S, max_keys: int = MAX_KEYS,
                 clock=time.monotonic) -> None:
        self._window = window_s
        self._max = max_keys
        self._clock = clock
        self._entries: "OrderedDict[str, _Entry]" = OrderedDict()
        self._lock = threading.Lock()

    def seen(self, token: str, client: Optional[str]) -> bool:
        key = _key(token, client)
        with self._lock:
            entry = self._entries.get(key)
            return entry is not None and self._clock() - entry.last_logged < self._window

    def refused(self, token: str, client: Optional[str]) -> Verdict:
        key = _key(token, client)
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and now - entry.last_logged < self._window:
                entry.folded += 1
                self._entries.move_to_end(key)
                return Verdict(known=True, log=False, repeats=entry.folded)
            repeats = entry.folded if entry is not None else 0
            self._entries[key] = _Entry(last_logged=now)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max:
                self._entries.popitem(last=False)
            return Verdict(known=entry is not None, log=True, repeats=repeats)


DEAD_TOKENS = DeadTokenLog()


def presented_token(raw_header: Optional[str], marker: str) -> Optional[str]:
    if not raw_header:
        return None
    parts = [p.strip() for p in raw_header.split(",") if p.strip()]
    others = [p for p in parts if p != marker]
    return others[0] if marker in parts and others else None


def short_agent(user_agent: Optional[str]) -> Optional[str]:
    return user_agent[:UA_MAX] if user_agent else None
