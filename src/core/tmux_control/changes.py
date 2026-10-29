
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Dict, List

import structlog

logger = structlog.get_logger()

CHANGE_NOTIFICATIONS = frozenset({
    "sessions-changed", "session-renamed", "window-add", "window-close", "window-renamed",
    "unlinked-window-add", "unlinked-window-close", "unlinked-window-renamed",
})

DEBOUNCE_SECONDS = 0.15

_LISTENERS: List[Callable[[str], None]] = []
_ARMED: Dict[str, "asyncio.TimerHandle"] = {}


def add_listener(listener: Callable[[str], None]) -> None:
    if listener not in _LISTENERS:
        _LISTENERS.append(listener)


def remove_listener(listener: Callable[[str], None]) -> None:
    if listener in _LISTENERS:
        _LISTENERS.remove(listener)


def emit(socket_name: str, name: str, delay: float = DEBOUNCE_SECONDS) -> None:
    if name not in CHANGE_NOTIFICATIONS or socket_name in _ARMED:
        return
    _ARMED[socket_name] = asyncio.get_running_loop().call_later(delay, _fire, socket_name)


def wake_listener(wake: Callable[[], None]) -> Callable[[str], None]:
    def listener(socket_name: str) -> None:
        from src.core import ttl_flight
        from src.core.sessions.pane_listing_cache import invalidate_pane_listing

        invalidate_pane_listing(socket_name)
        ttl_flight.invalidate_all()
        wake()

    return listener


def _fire(socket_name: str) -> None:
    _ARMED.pop(socket_name, None)
    for listener in list(_LISTENERS):
        try:
            listener(socket_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("tmux_change_listener_failed", error=str(exc), error_type=type(exc).__name__)


def control_feed(socket_name: Callable[[], str],
                 local_only: Callable[[], bool] = lambda: True) -> Callable[[], Awaitable[bool]]:
    async def feed() -> bool:
        from src.core.tmux_control.client import get_control_input
        from src.core.tmux_control.names import control_input_enabled

        if not control_input_enabled() or not local_only():
            return False
        return await get_control_input(socket_name()).listen()

    return feed
