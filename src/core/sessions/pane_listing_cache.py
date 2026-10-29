
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Generic, Iterable, Optional, TypeVar

T = TypeVar("T")

PANE_LISTING_TTL_SECONDS = 1.0

MUTATING_TMUX_VERBS = frozenset({
    "new-session", "kill-session", "kill-server", "kill-pane", "kill-window",
    "respawn-pane", "respawn-window", "rename-session", "new-window",
    "split-window", "break-pane", "join-pane", "move-pane", "move-window",
    "swap-pane", "swap-window", "source-file", "start-server", "run-shell",
})


def args_mutate_sessions(args: Iterable[str]) -> bool:
    return any(arg in MUTATING_TMUX_VERBS for arg in args)


@dataclass
class _Flight:

    generation: int
    done: threading.Event = field(default_factory=threading.Event)
    value: object = None
    error: Optional[BaseException] = None


class PaneListingCache(Generic[T]):

    def __init__(self, ttl_seconds: float = PANE_LISTING_TTL_SECONDS,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._stored: Dict[str, tuple] = {}
        self._flights: Dict[str, _Flight] = {}
        self._generation: Dict[str, int] = {}

    def get(self, key: str, loader: Callable[[], T], *, fresh: bool = False,
            cacheable: Callable[[T], bool] = lambda value: True) -> T:
        while True:
            with self._lock:
                gen = self._generation.get(key, 0)
                if not fresh:
                    hit = self._stored.get(key)
                    if hit is not None and hit[1] == gen and self._clock() - hit[0] < self._ttl:
                        return hit[2]
                    flight = self._flights.get(key)
                    if flight is not None and flight.generation == gen:
                        waiting_on: Optional[_Flight] = flight
                    else:
                        waiting_on = None
                else:
                    waiting_on = None
                if waiting_on is None:
                    mine = _Flight(generation=gen)
                    if not fresh:
                        self._flights[key] = mine
            if waiting_on is not None:
                waiting_on.done.wait()
                if waiting_on.error is None:
                    return waiting_on.value  # type: ignore[return-value]
                continue
            return self._lead(key, mine, loader, fresh, cacheable)

    def _lead(self, key: str, mine: _Flight, loader: Callable[[], T], fresh: bool,
              cacheable: Callable[[T], bool]) -> T:
        try:
            value = loader()
        except BaseException as exc:
            mine.error = exc
            raise
        else:
            mine.value = value
            with self._lock:
                if mine.generation == self._generation.get(key, 0) and cacheable(value):
                    self._stored[key] = (self._clock(), mine.generation, value)
            return value
        finally:
            with self._lock:
                if self._flights.get(key) is mine:
                    del self._flights[key]
            mine.done.set()

    def invalidate(self, key: Optional[str] = None) -> None:
        with self._lock:
            keys = [key] if key is not None else list(
                set(self._stored) | set(self._flights) | set(self._generation))
            for each in keys:
                self._generation[each] = self._generation.get(each, 0) + 1
                self._stored.pop(each, None)
                self._flights.pop(each, None)


PANE_LISTING_CACHE: PaneListingCache = PaneListingCache()


def invalidate_pane_listing(socket_name: Optional[str] = None) -> None:
    PANE_LISTING_CACHE.invalidate(socket_name)
