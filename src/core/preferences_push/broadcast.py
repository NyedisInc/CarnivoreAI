from __future__ import annotations

import json
from typing import Any, Optional

import structlog

from src.core import session_change_notice, ui_preferences, ui_preferences_store
from src.models import WSMessageType

logger = structlog.get_logger()

PREFERENCES_CHANGED_EVENT = WSMessageType.PREFERENCES_CHANGED.value


async def broadcast_changed(
    app_state: Any,
    result: ui_preferences_store.UpdateResult,
    client_id: Optional[str],
) -> None:
    manager = getattr(app_state, "connection_manager", None)
    if manager is None:
        return

    frame = {
        "type": PREFERENCES_CHANGED_EVENT,
        "schema_version": ui_preferences.SCHEMA_VERSION,
        "revision": result.revision,
        "changed": result.changed,
        "origin_client_id": client_id,
    }
    session_change_notice.publish(app_state, frame)

    try:
        await manager.broadcast(json.dumps(frame))
    except (TypeError, ValueError) as exc:
        logger.error(
            "preferences_changed_broadcast_unencodable",
            revision=result.revision,
            fields=sorted(result.changed.keys()),
            error=str(exc),
        )
    except OSError as exc:
        logger.warning(
            "preferences_changed_broadcast_failed",
            revision=result.revision,
            error=str(exc),
        )
