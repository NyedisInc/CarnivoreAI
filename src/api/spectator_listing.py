"""Stamping the session listing with whether a session is shared.

WHY THE LISTING CARRIES THIS AT ALL. The sidebar draws a mark on a
session that somebody outside this install can currently watch, and the
alternative - one spectator-links request per row - would turn the most
polled endpoint in the app into N+1 of them. One query per listing pass
answers it for every row at once.

IT NEVER FAILS THE LISTING, AND "ABSENT" IS NOT THE ONLY WAY THIS CAN
GO WRONG. The spectator store is optional application state: an install
that never opened it still lists its sessions, and a listing that 500ed
because an optional store was missing would take the whole home screen
down over a feature nobody was using. A store that is PRESENT AND BROKEN
- a disk I/O error, a locked database, a store whose ``init()`` never
ran - has exactly the same blast radius, so it gets exactly the same
answer: every row unstamped, the listing served, and one log line naming
what happened. The catch is NARROW on purpose (CLAUDE.md, "How we work
here"): the database errors and the uninitialised-store assertion, so a
TypeError in this module's own code still surfaces as one.

THE FIELD IS ON THE WRAPPER, not on ``.session``. See CLAUDE.md, "The
/sessions/list shape".
"""

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
