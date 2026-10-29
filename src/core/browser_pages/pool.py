
from __future__ import annotations

import itertools
import threading
from dataclasses import dataclass
from typing import List, Optional

POOL_SIZE = 2


@dataclass
class _Slot:

    browser_id: str
    key: str
    used: int


_lock = threading.Lock()
_slots: List[_Slot] = []
_clock = itertools.count(1)


def page_key(kind: str, ref: str) -> str:
    return f"{kind}:{ref}"


def plan(key: str) -> Optional[str]:
    with _lock:
        for slot in _slots:
            if slot.key == key:
                return slot.browser_id
        if len(_slots) < POOL_SIZE:
            return None
        return min(_slots, key=lambda s: s.used).browser_id


def fallback(exclude: str = "") -> Optional[str]:
    with _lock:
        others = [s for s in _slots if s.browser_id != exclude]
        return min(others, key=lambda s: s.used).browser_id if others else None


def remember(browser_id: str, key: str) -> None:
    with _lock:
        for slot in _slots:
            if slot.browser_id == browser_id:
                slot.key, slot.used = key, next(_clock)
                break
        else:
            _slots.append(_Slot(browser_id, key, next(_clock)))
        _slots[:] = [s for s in _slots if s.browser_id == browser_id or s.key != key]


def forget(browser_id: str) -> None:
    with _lock:
        _slots[:] = [s for s in _slots if s.browser_id != browser_id]


def members() -> List[str]:
    with _lock:
        return [s.browser_id for s in sorted(_slots, key=lambda s: s.used)]


def reset_for_test() -> None:
    with _lock:
        _slots.clear()


__all__ = ["POOL_SIZE", "fallback", "forget", "members", "page_key", "plan", "remember", "reset_for_test"]
