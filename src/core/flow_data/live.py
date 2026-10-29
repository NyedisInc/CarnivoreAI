
from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Callable, Dict, Iterable, Optional

import structlog

from src.cplugs.sdk import transcript_events

logger = structlog.get_logger()

TOPIC = "feed"
LEASE_S = 45.0
KEEPALIVE_S = 20.0


class FeedWatch:

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._keys: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._notify: Optional[Callable[[], None]] = None
        self._unsubscribe: Optional[Callable[[], None]] = None
        self._armed = False

    def take(self, notify: Callable[[], None], keys: Iterable[Optional[str]], loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        until = self._clock() + LEASE_S
        with self._lock:
            for key in keys:
                if key:
                    self._keys[key] = until
            self._notify = notify
            if self._unsubscribe is None:
                self._unsubscribe = transcript_events.subscribe(self._on_append)
            arm = not self._armed
            self._armed = True
        if arm:
            self._arm(loop)

    def _arm(self, loop: Optional[asyncio.AbstractEventLoop]) -> None:
        try:
            target = loop or asyncio.get_running_loop()
        except RuntimeError:
            with self._lock:
                self._armed = False
            return
        target.call_later(KEEPALIVE_S, self._keepalive, target)

    def _live(self, now: float) -> bool:
        for key in [k for k, until in self._keys.items() if until <= now]:
            del self._keys[key]
        return bool(self._keys)

    def _on_append(self, session_id: str, tmux_name: Optional[str]) -> None:
        with self._lock:
            if not self._live(self._clock()):
                self._stop_locked()
                return
            hit = session_id in self._keys or (tmux_name is not None and tmux_name in self._keys)
            notify = self._notify
        if hit and notify is not None:
            notify()

    def _keepalive(self, loop: asyncio.AbstractEventLoop) -> None:
        with self._lock:
            live = self._live(self._clock())
            notify = self._notify
            if not live:
                self._stop_locked()
                self._armed = False
        if not live:
            return
        if notify is not None:
            notify()
        loop.call_later(KEEPALIVE_S, self._keepalive, loop)

    def _stop_locked(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        self._keys.clear()

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def leased(self) -> Dict[str, Any]:
        with self._lock:
            self._live(self._clock())
            return {"keys": sorted(self._keys), "subscribed": self._unsubscribe is not None}


WATCH = FeedWatch()
BUILTIN_OWNER = "flow"
_OWNERS: Dict[str, FeedWatch] = {}
_OWNERS_LOCK = threading.Lock()


def watch_for(owner: str, clock: Optional[Callable[[], float]] = None) -> FeedWatch:
    with _OWNERS_LOCK:
        found = _OWNERS.get(owner)
        if found is None:
            found = _OWNERS[owner] = FeedWatch(clock) if clock else FeedWatch()
        return found


def drop_owners(prefix: str) -> None:
    with _OWNERS_LOCK:
        gone = [name for name in _OWNERS if name.startswith(prefix)]
        watches = [_OWNERS.pop(name) for name in gone]
    for watch in watches:
        watch.stop()
