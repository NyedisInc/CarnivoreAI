from __future__ import annotations

from typing import Any, Callable, Optional

import structlog

from src.core.hosts.tmux_quote import TmuxQuoteError
from src.core.session_backend import SessionBackend
from src.core.sessions.errors import SessionInputFailed
from src.models.sessions import Session
from src.models.utc_time import utc_now

logger = structlog.get_logger()

BACKEND_WRITE_ERRORS = (OSError, RuntimeError, TmuxQuoteError)


async def deliver_to_pane(
    backend: SessionBackend,
    session: Session,
    session_id: str,
    payload: bytes,
    *,
    what: str,
    after_delivery: Optional[Callable[[], None]] = None,
) -> bool:
    try:
        await backend.write(payload)
    except BACKEND_WRITE_ERRORS as e:
        logger.error(f"send_{what}_failed", session_id=session_id, error=str(e), error_type=type(e).__name__)
        raise SessionInputFailed(f"Failed to send {what}: {e}") from e
    session.last_activity = utc_now()
    if after_delivery is not None:
        after_delivery()
    return True


def book_command_delivery(count_command: Callable[[str], None], save_metadata: Callable[[Any], None], session_id: str, session: Any) -> None:
    count_command(session_id)
    save_metadata(session)

