
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

_MILLISECOND_FLOOR = 1e12


def parse_reset_at(value: object) -> Optional[datetime]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return _from_epoch(float(value))
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None
    try:
        return _from_epoch(float(text))
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_retry_after_seconds(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        seconds = float(value.strip())
    except (ValueError, AttributeError):
        return None
    if seconds <= 0:
        return None
    return seconds


def _from_epoch(raw: float) -> Optional[datetime]:
    seconds = raw / 1000.0 if abs(raw) >= _MILLISECOND_FLOOR else raw
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def read_percent(value: object) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
