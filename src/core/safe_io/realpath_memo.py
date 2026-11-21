
from __future__ import annotations

import os
import threading
import time
from typing import Dict, Tuple, Union

TTL_S = 30.0
MAX_ENTRIES = 4096

_lock = threading.Lock()
_entries: Dict[str, Tuple[str, float]] = {}


def _prune(now: float) -> None:
    for key in [k for k, (_, at) in _entries.items() if now - at >= TTL_S]:
        del _entries[key]
    if len(_entries) >= MAX_ENTRIES:
        _entries.clear()


def realpath(path: Union[str, "os.PathLike[str]"]) -> str:
    key = os.fspath(path)
    if not os.path.isabs(key):
        return os.path.realpath(key)
    now = time.monotonic()
    with _lock:
        hit = _entries.get(key)
    if hit is not None and now - hit[1] < TTL_S:
        return hit[0]
    resolved = os.path.realpath(key)
    with _lock:
        if len(_entries) >= MAX_ENTRIES:
            _prune(now)
        _entries[key] = (resolved, now)
    return resolved


def clear() -> None:
    with _lock:
        _entries.clear()
