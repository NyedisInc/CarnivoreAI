
from __future__ import annotations

import re
from typing import Any, Callable, Mapping, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog

logger = structlog.get_logger()

PREFERENCE_FIELD: str = "time_zone"
DEFAULT_NAME: str = "America/New_York"
NAME_RE = re.compile(r"^[A-Za-z0-9_+\-]+(?:/[A-Za-z0-9_+\-]+){0,2}$")
MAX_NAME_CHARS: int = 64

_last_name: str = DEFAULT_NAME
_read_preferences: Optional[Callable[[], Mapping[str, Any]]] = None


def validate(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_NAME_CHARS or not NAME_RE.match(value):
        raise ValueError("time_zone must be an IANA zone name such as America/New_York")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise ValueError("time_zone is not a time zone this server knows") from exc
    return value


def install(read_preferences: Callable[[], Mapping[str, Any]]) -> None:
    global _read_preferences
    _read_preferences = read_preferences


def uninstall() -> None:
    global _read_preferences, _last_name
    _read_preferences = None
    _last_name = DEFAULT_NAME


def name() -> str:
    global _last_name
    if _read_preferences is None:
        return DEFAULT_NAME
    try:
        values = _read_preferences().get("values")
    except (OSError, ValueError) as exc:
        logger.error("app_time_zone_unreadable", error_type=type(exc).__name__, error=str(exc)[:300])
        return _last_name
    stored = values.get(PREFERENCE_FIELD) if isinstance(values, Mapping) else None
    if stored is None:
        _last_name = DEFAULT_NAME
        return _last_name
    try:
        _last_name = validate(stored)
    except ValueError as exc:
        logger.warning("app_time_zone_invalid_stored", error=str(exc)[:200])
        _last_name = DEFAULT_NAME
    return _last_name


def zone() -> ZoneInfo:
    return ZoneInfo(name())
