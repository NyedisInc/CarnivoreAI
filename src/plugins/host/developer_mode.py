
from __future__ import annotations

import structlog

logger = structlog.get_logger()


def is_on() -> bool:
    from src.config import settings  # noqa: PLC0415

    try:
        return bool(settings.load_auth_config().server_prefs.developer_mode)
    except (FileNotFoundError, ValueError, OSError) as exc:
        logger.warning("developer_mode_config_unreadable", error_type=type(exc).__name__)
        return False
