
from __future__ import annotations

from typing import Any

import structlog

from src.cplugs.sdk import ports
from src.core.session_roles.read import PORT

logger = structlog.get_logger()
_PORT_ERRORS = (OSError, RuntimeError, ValueError, LookupError, AttributeError, PermissionError)


async def after_change(app_state: Any) -> None:
    port = ports.get(PORT)
    if port is None:
        return
    try:
        await port.check_gone(app_state)
    except _PORT_ERRORS as exc:
        logger.warning("session_roles.check.failed", error=type(exc).__name__)
