
from __future__ import annotations

from typing import Optional, Tuple

import structlog

from src.config import settings
from src.core.scrollback_replay import with_cursor_restore

logger = structlog.get_logger()

MAX_SCROLLBACK_LINES = 50000


def resize_and_capture(
    session_manager,
    *,
    session_id: str,
    cols: Optional[int],
    rows: Optional[int],
    lines: Optional[int] = None,
) -> bytes:
    if cols and rows and cols > 0 and rows > 0:
        try:
            session_manager.resize_terminal(
                cols=cols, rows=rows, session_id=session_id
            )
        except Exception as exc:
            logger.warning(
                "rejoin_pre_resize_failed",
                session_id=session_id,
                cols=cols,
                rows=rows,
                error=str(exc),
            )

    try:
        depth = (
            min(lines, MAX_SCROLLBACK_LINES)
            if lines and lines > 0
            else settings.load_auth_config().session.scrollback_lines
        )
        raw = session_manager.capture_scrollback(
            lines=depth,
            session_id=session_id,
        )
    except Exception as exc:
        logger.warning(
            "rejoin_scrollback_capture_failed",
            session_id=session_id,
            error=str(exc),
        )
        return b""

    return with_cursor_restore(raw, pane_cursor(session_manager, session_id))


def pane_cursor(session_manager, session_id: str) -> Optional[Tuple[int, int]]:
    backend = session_manager._registry.get_backend(session_id)
    reader = getattr(backend, "pane_cursor_position", None)
    if reader is None:
        return None
    try:
        cursor = reader()
    except Exception as exc:
        logger.warning(
            "rejoin_cursor_read_failed", session_id=session_id, error=str(exc)
        )
        return None
    if (
        isinstance(cursor, tuple)
        and len(cursor) == 2
        and all(isinstance(value, int) for value in cursor)
    ):
        return cursor
    return None
