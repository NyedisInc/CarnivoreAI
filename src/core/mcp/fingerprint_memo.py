
from __future__ import annotations

import threading
import time
from typing import Callable, Dict, Hashable, Tuple

TTL_S = 2.0
MAX_ENTRIES = 512

_lock = threading.Lock()
_entries: Dict[Hashable, Tuple[str, float]] = {}
_generation = 0


def remembered(key: Hashable, compute: Callable[[], str]) -> str:
    now = time.monotonic()
    with _lock:
        hit = _entries.get(key)
        started = _generation
    if hit is not None and now - hit[1] < TTL_S:
        return hit[0]
    value = compute()
    with _lock:
        if started == _generation:
            if len(_entries) >= MAX_ENTRIES:
                _entries.clear()
            _entries[key] = (value, now)
    return value


def clear() -> None:
    global _generation
    with _lock:
        _generation += 1
        _entries.clear()
