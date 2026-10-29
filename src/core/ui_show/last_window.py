
from __future__ import annotations

import re
import threading
import time
from typing import Optional

CLIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

MAX_WINDOWS = 16

_lock = threading.Lock()
_recent: list[tuple[str, float]] = []


def valid_client_id(value: object) -> bool:
    return isinstance(value, str) and bool(CLIENT_ID_PATTERN.match(value))


def touch(client_id: str, now: Optional[float] = None) -> None:
    if not valid_client_id(client_id):
        raise ValueError("not a client id")
    with _lock:
        _recent[:] = [(cid, at) for cid, at in _recent if cid != client_id]
        _recent.insert(0, (client_id, time.time() if now is None else now))
        del _recent[MAX_WINDOWS:]


def current() -> Optional[str]:
    with _lock:
        return _recent[0][0] if _recent else None


def known(client_id: str) -> bool:
    with _lock:
        return any(cid == client_id for cid, _ in _recent)


def gone(client_id: str) -> bool:
    if not valid_client_id(client_id):
        raise ValueError("not a client id")
    with _lock:
        before = len(_recent)
        _recent[:] = [(cid, at) for cid, at in _recent if cid != client_id]
        return len(_recent) != before


def reset_for_test() -> None:
    with _lock:
        _recent.clear()
