
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Iterable, Optional

import structlog

logger = structlog.get_logger()


def iso_utc(unix_seconds: Optional[int]) -> Optional[str]:
    if unix_seconds is None:
        return None
    return datetime.fromtimestamp(int(unix_seconds), tz=timezone.utc).isoformat()


async def mark_shared(app_state, infos: Iterable) -> None:
    store = getattr(app_state, "spectator_links", None)
    if store is None:
        return
    try:
        expiry = await store.live_expiry_by_session()
    except (sqlite3.Error, AssertionError) as exc:
        logger.warning(
            "spectator_listing_mark_failed",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return
    for info in infos:
        info.spectator_expires_at = iso_utc(expiry.get(info.session.id))
