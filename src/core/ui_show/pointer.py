
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

from src.core import resource_push
from src.core.resource_push.topics import UI_SHOW

FRESH_S = 60
MAX_TITLE = 120

_lock = threading.Lock()
_pointer: Optional[Dict[str, Any]] = None


def current(now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    with _lock:
        found = dict(_pointer) if _pointer else None
    if found is not None:
        found["age_s"] = max(0.0, round((time.time() if now is None else now) - found["at"], 3))
    return found


def point(kind: str, item_id: str, title: str, target_client_id: str, tmux_session: Optional[str] = None) -> Dict[str, Any]:
    global _pointer
    stored = {"seq": time.time_ns() // 1000, "kind": kind, "id": item_id, "tmux_session": tmux_session,
              "title": title[:MAX_TITLE], "target_client_id": target_client_id, "at": time.time()}
    with _lock:
        _pointer = stored
    resource_push.notify(UI_SHOW)
    return current() or stored


def reset_for_test() -> None:
    global _pointer
    with _lock:
        _pointer = None
