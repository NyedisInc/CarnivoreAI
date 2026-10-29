
from __future__ import annotations

from datetime import datetime
from typing import Optional

PACE_MIN_ELAPSED_PCT = 5.0
PACE_OVERRUN_PROJECTION_PCT = 120.0

_HOUR_S = 3600
_DAY_S = 24 * _HOUR_S


def window_length_seconds(kind: str, label: str, window_seconds: Optional[int]) -> Optional[int]:
    if window_seconds and window_seconds > 0:
        return window_seconds
    tag = label.strip().lower()
    if kind == "five_hour" or tag in ("5h", "five_hour"):
        return 5 * _HOUR_S
    if kind.startswith("seven_day") or tag == "7d":
        return 7 * _DAY_S
    return None


def elapsed_pct(length_s: Optional[int], resets_at: Optional[datetime], now: datetime) -> Optional[float]:
    if not length_s or resets_at is None:
        return None
    remaining = (resets_at - now).total_seconds()
    if remaining <= 0:
        return None
    return min(100.0, max(0.0, (1 - remaining / length_s) * 100))


def pace_state(used_pct: Optional[float], elapsed: Optional[float]) -> Optional[str]:
    if used_pct is None or elapsed is None:
        return None
    if used_pct >= 100:
        return "over"
    if elapsed < PACE_MIN_ELAPSED_PCT or used_pct <= elapsed:
        return "on"
    return "over" if used_pct / elapsed * 100 >= PACE_OVERRUN_PROJECTION_PCT else "ahead"
