
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

import structlog

from src.cplugs.sdk import ports

logger = structlog.get_logger()

PORT = "session.schedules"
_PORT_ERRORS = (OSError, RuntimeError, ValueError, LookupError, AttributeError, PermissionError)


class PluginSchedulesUnreadable(Exception):
    pass


async def read(infos: Iterable[Any], asleep: Optional[List[Dict[str, Any]]] = None) -> Dict[str, List[Dict[str, Any]]]:
    port = ports.get(PORT)
    if port is None:
        return {}
    try:
        return await port.by_session(list(infos)) if asleep is None else await port.by_session(list(infos), asleep=asleep)
    except _PORT_ERRORS as exc:
        logger.warning("listing.plugin_schedules.unreadable", error=type(exc).__name__)
        raise PluginSchedulesUnreadable(type(exc).__name__) from exc


async def wake_entries(asleep: List[Dict[str, Any]], infos: Optional[List[Any]] = None, app_state: Any = None) -> Dict[str, List[Dict[str, Any]]]:
    port = ports.get(PORT)
    if port is None or not hasattr(port, "wake_entries"):
        return {}
    try:
        return await port.wake_entries(list(asleep), infos, app_state)
    except _PORT_ERRORS as exc:
        logger.warning("listing.plugin_wakes.unreadable", error=type(exc).__name__)
        raise PluginSchedulesUnreadable(type(exc).__name__) from exc
