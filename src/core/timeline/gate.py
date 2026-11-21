
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable, List

import structlog

from src.core.product_identity import env_value

log = structlog.get_logger(__name__)

HOOK_TTL_SECONDS: float = 5.0


STATUS_SOURCE_ENV: str = "TIMELINE_STATUS_SOURCE"
SOURCE_LEGACY, SOURCE_SHADOW, SOURCE_FOLD = "legacy", "shadow", "fold"
DEFAULT_SOURCE: str = SOURCE_SHADOW


class TimelineOff(Exception):
    pass


def switch_on() -> bool:
    from src.config import settings  # noqa: PLC0415
    from src.core.pipeline import switch  # noqa: PLC0415
    from src.core.timeline.plugin import TIMELINE  # noqa: PLC0415

    return switch.is_on(TIMELINE, Path(settings.get_state_dir()))


def require_on() -> None:
    if not switch_on():
        raise TimelineOff("the session timeline is off; turn on session chat in settings, features")


class _Memo:

    def __init__(self) -> None:
        self.on = False
        self.read_at = float("-inf")
        self.lock = threading.Lock()


_MEMO = _Memo()


def status_source() -> str:
    value = (env_value(STATUS_SOURCE_ENV) or "").strip().lower()
    return value if value in (SOURCE_LEGACY, SOURCE_SHADOW, SOURCE_FOLD) else DEFAULT_SOURCE


_off_listeners: List[Callable[[], None]] = []


def on_off(listener: Callable[[], None]) -> None:
    _off_listeners.append(listener)


def fire_off() -> None:
    for listener in list(_off_listeners):
        try:
            listener()
        except Exception as exc:  # noqa: BLE001
            log.error("timeline_off_cleanup_failed", error=type(exc).__name__, exc_info=True)


def hook_on(*, clock: Callable[[], float] = time.monotonic) -> bool:
    if status_source() == SOURCE_LEGACY:
        return False
    now = clock()
    with _MEMO.lock:
        if now - _MEMO.read_at < HOOK_TTL_SECONDS:
            return _MEMO.on
    on = switch_on()
    with _MEMO.lock:
        was, _MEMO.on, _MEMO.read_at = _MEMO.on, on, now
    if was and not on:
        fire_off()
    return on


def reset_hook_gate() -> None:
    with _MEMO.lock:
        _MEMO.on, _MEMO.read_at = False, float("-inf")
