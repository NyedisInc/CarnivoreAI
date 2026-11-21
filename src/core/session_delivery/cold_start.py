
from __future__ import annotations

import time
from typing import Dict, Optional

COLD_WINDOW_S: float = 180.0

_READY_AT: Dict[str, float] = {}


def mark_brought_up(session_id: str, now: Optional[float] = None) -> None:
    stamp = time.monotonic() if now is None else now
    for sid in [s for s, at in _READY_AT.items() if stamp - at > COLD_WINDOW_S]:
        del _READY_AT[sid]
    _READY_AT[session_id] = stamp


def is_cold(session_id: str, now: Optional[float] = None) -> bool:
    at = _READY_AT.get(session_id)
    return at is not None and (time.monotonic() if now is None else now) - at <= COLD_WINDOW_S
