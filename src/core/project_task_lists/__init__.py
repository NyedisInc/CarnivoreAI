
from __future__ import annotations

from typing import Any, Dict, Optional

import structlog

logger = structlog.get_logger()

_PORT_ERRORS = (OSError, RuntimeError, ValueError, LookupError, AttributeError, PermissionError)


def clear_for_deleted_project(project_id: int) -> Optional[Dict[str, Any]]:
    from src.plugins.sdk import ports  # noqa: PLC0415
    from src.plugins.sdk.project_lists import NAME  # noqa: PLC0415

    port = ports.get(NAME)
    if port is None:
        return None
    try:
        return port.clear(project_id)
    except _PORT_ERRORS as exc:
        logger.warning("project_task_list_clear_failed", project_id=project_id, error_type=type(exc).__name__, error=str(exc))
        return None
