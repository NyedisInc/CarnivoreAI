
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

import structlog

from src.cplugs.sdk import ports

logger = structlog.get_logger()

PORT = "session.roles"
_PORT_ERRORS = (OSError, RuntimeError, ValueError, LookupError, AttributeError, PermissionError)


class SessionRolesUnreadable(Exception):
    """A plugin offered its roles and could not read them: the row's word is then not measured, never a partial answer."""


async def read(app_state: Any, infos: Iterable[Any], asleep: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Dict[str, bool]]]:
    port = ports.get(PORT)
    if port is None:
        return None
    try:
        return await port.read(app_state, list(infos)) if asleep is None else await port.read(app_state, list(infos), asleep=asleep)
    except _PORT_ERRORS as exc:
        logger.warning("listing.session_roles.unreadable", error=type(exc).__name__)
        raise SessionRolesUnreadable(type(exc).__name__) from exc
