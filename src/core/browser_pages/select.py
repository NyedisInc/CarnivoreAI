
from __future__ import annotations

import threading
import time
from typing import Optional

from src.core import resource_push
from src.core.resource_push.topics import BROWSER_SELECT

FRESH_S = 60
MAX_TITLE = 120

_lock = threading.Lock()
_pointer: Optional[dict] = None


def current(now: Optional[float] = None) -> Optional[dict]:
    with _lock:
        found = dict(_pointer) if _pointer else None
    if found is not None:
        found["age_s"] = max(0.0, round((time.time() if now is None else now) - found["at"], 3))
    return found


def _store(fields: dict, title: str) -> dict:
    global _pointer
    stored = {**fields, "title": title[:MAX_TITLE], "seq": time.time_ns() // 1000, "at": time.time()}
    with _lock:
        _pointer = stored
    resource_push.notify(BROWSER_SELECT)
    return current() or stored


def select(browser_id: str, title: str) -> dict:
    return _store({"kind": "browser", "browser_id": browser_id}, title)


def select_page(page_id: str, title: str) -> dict:
    return _store({"kind": "page", "page_id": page_id}, title)


def reset_for_test() -> None:
    global _pointer
    with _lock:
        _pointer = None


__all__ = ["FRESH_S", "MAX_TITLE", "current", "reset_for_test", "select", "select_page"]
