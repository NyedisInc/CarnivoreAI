
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional, Tuple

import structlog

LEVEL_NAMES: Tuple[str, ...] = ("error", "warn", "info", "debug")

_NAME_TO_NUMBER: Dict[str, int] = {
    "error": logging.ERROR,
    "warn": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
}

DEFAULT_LEVEL = "info"

_METHOD_LEVELS: Dict[str, int] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "msg": logging.INFO,
    "warning": logging.WARNING,
    "warn": logging.WARNING,
    "error": logging.ERROR,
    "exception": logging.ERROR,
    "fatal": logging.ERROR,
    "critical": logging.CRITICAL,
}

_current: int = logging.INFO


def current_number() -> int:
    return _current


def name_for_number(number: int) -> str:
    if number <= logging.DEBUG:
        return "debug"
    if number <= logging.INFO:
        return "info"
    if number <= logging.WARNING:
        return "warn"
    return "error"


def normalize(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if text == "warning":
        text = "warn"
    elif text in ("critical", "fatal"):
        text = "error"
    return text if text in _NAME_TO_NUMBER else None


def number_for(name: str) -> int:
    return _NAME_TO_NUMBER[name]


def apply_level(name: str) -> int:
    global _current
    number = _NAME_TO_NUMBER[name]
    _current = number
    logging.getLogger().setLevel(number)
    return number


def _gated(method: Callable[..., Any], level: int) -> Callable[..., Any]:

    def gated(self: Any, *args: Any, **kw: Any) -> Any:
        if level < _current:
            return None
        return method(self, *args, **kw)

    gated.__name__ = method.__name__
    return gated


def _agated(method: Callable[..., Any], level: int) -> Callable[..., Any]:

    async def agated(self: Any, *args: Any, **kw: Any) -> Any:
        if level < _current:
            return None
        return await method(self, *args, **kw)

    agated.__name__ = method.__name__
    return agated


def _build_logger_class() -> type:
    base = structlog.make_filtering_bound_logger(logging.DEBUG)
    members: Dict[str, Any] = {}
    for name, level in _METHOD_LEVELS.items():
        members[name] = _gated(getattr(base, name), level)
        members[f"a{name}"] = _agated(getattr(base, f"a{name}"), level)

    base_log, base_alog = base.log, base.alog

    def log(self: Any, level: int, *args: Any, **kw: Any) -> Any:
        if level < _current:
            return None
        return base_log(self, level, *args, **kw)

    async def alog(self: Any, level: int, *args: Any, **kw: Any) -> Any:
        if level < _current:
            return None
        return await base_alog(self, level, *args, **kw)

    def is_enabled_for(self: Any, level: int) -> bool:
        return level >= _current

    def get_effective_level(self: Any) -> int:
        return _current

    members.update(
        log=log, alog=alog, is_enabled_for=is_enabled_for, get_effective_level=get_effective_level
    )
    return type("LiveLevelBoundLogger", (base,), members)


LiveLevelBoundLogger = _build_logger_class()


def announce(logger: Any, event: str, **kw: Any) -> None:
    bound = logger.bind()
    if isinstance(bound, LiveLevelBoundLogger):
        super(LiveLevelBoundLogger, bound).info(event, **kw)
    else:
        bound.info(event, **kw)
