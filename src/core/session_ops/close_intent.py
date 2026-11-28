from __future__ import annotations

import threading
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterator, List, Optional, Tuple

from src.core import restart_inflight
from src.core.restart_inflight import HISTORY_SECONDS

InstanceKey = Tuple[str, str, str, Optional[int]]

LINGER_SECONDS = 600.0

_lock = threading.Lock()
_active: "Counter[InstanceKey]" = Counter()
_ended: List[Tuple[InstanceKey, float]] = []
_lingering: Dict[InstanceKey, Tuple[float, float]] = {}


@dataclass
class StopMark:

    settled: bool = False


def _same(held: InstanceKey, host: str, socket: str, name: str, epoch: Optional[int]) -> bool:
    h_host, h_socket, h_name, h_epoch = held
    return (h_host, h_socket, h_name) == (host, socket, name) and (h_epoch is None or epoch is None or h_epoch == epoch)


def _prune(now: float) -> None:
    _ended[:] = [(k, t) for k, t in _ended if now - t <= HISTORY_SECONDS]
    for key in [k for k, (_, deadline) in _lingering.items() if deadline <= now]:
        del _lingering[key]


@contextmanager
def stopping(host: str, socket: Optional[str], name: Optional[str], epoch: Optional[int]) -> Iterator[StopMark]:
    mark = StopMark()
    key: Optional[InstanceKey] = (host, socket, name, epoch) if socket and name else None
    if key is not None:
        with _lock:
            _active[key] += 1
    try:
        yield mark
    finally:
        if key is not None:
            now = time.monotonic()
            with _lock:
                _active[key] -= 1
                if _active[key] <= 0:
                    del _active[key]
                _ended.append((key, now))
                if not mark.settled and key[3] is not None:
                    _lingering[key] = (now, now + LINGER_SECONDS)
                _prune(now)


def keep_stopped(host: str, socket: str, name: str, epoch: Optional[int]) -> None:
    if epoch is None:
        return
    now = time.monotonic()
    with _lock:
        _lingering[(host, socket, name, epoch)] = (now, now + LINGER_SECONDS)
        _prune(now)


def release_recorded(host: str, socket: str, name: str, epoch: Optional[int]) -> None:
    with _lock:
        for key in [k for k in _lingering if _same(k, host, socket, name, epoch)]:
            del _lingering[key]


def release_stale(host: str, socket: str, name: str, epoch: Optional[int], measured_after: float) -> None:
    with _lock:
        for key in [k for k, (left_at, _) in _lingering.items()
                    if left_at < measured_after and _same(k, host, socket, name, epoch)]:
            del _lingering[key]


def stamp() -> float:
    return time.monotonic()


@dataclass(frozen=True)
class Touched:

    instances: FrozenSet[InstanceKey] = field(default_factory=frozenset)
    session_uuids: FrozenSet[str] = field(default_factory=frozenset)

    def covers(self, host: str, socket: str, name: Optional[str], epoch: Optional[int], session_uuid: Optional[str]) -> bool:
        if session_uuid and session_uuid in self.session_uuids:
            return True
        return bool(name) and any(_same(k, host, socket, str(name), epoch) for k in self.instances)


def touched_since(t0: float) -> Touched:
    now = time.monotonic()
    with _lock:
        _prune(now)
        keys = set(_active) | set(_lingering) | {k for k, ended in _ended if ended >= t0}
    return Touched(frozenset(keys), frozenset(restart_inflight.touched_since(t0)))
