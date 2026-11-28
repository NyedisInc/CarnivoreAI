
from __future__ import annotations

import functools
import threading
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Optional, TypeVar

import structlog

from src.plugins.save.offload import constants as C

logger = structlog.get_logger()

F = TypeVar("F", bound=Callable[..., Any])

_notifier: Optional[Callable[[str], None]] = None
_local = threading.local()


def bind(notify: Callable[[str], None]) -> None:
    global _notifier
    _notifier = notify


def unbind() -> None:
    global _notifier
    _notifier = None


def _fire() -> None:
    notify = _notifier
    if notify is None:
        return
    try:
        notify(C.PUSH_TOPIC)
    except (ValueError, RuntimeError, OSError) as exc:
        logger.warning("offload_push_failed", error_type=type(exc).__name__, error=str(exc)[:200])


def changed() -> None:
    if getattr(_local, "depth", 0) > 0:
        _local.dirty = True
        return
    _fire()


@contextmanager
def coalesced() -> Iterator[None]:
    _local.depth = getattr(_local, "depth", 0) + 1
    try:
        yield
    finally:
        _local.depth -= 1
        if _local.depth == 0 and getattr(_local, "dirty", False):
            _local.dirty = False
            _fire()


def coalescing(function: F) -> F:

    @functools.wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with coalesced():
            return function(*args, **kwargs)

    return wrapper  # type: ignore[return-value]
