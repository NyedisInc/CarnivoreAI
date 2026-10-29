
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from src.core.session_activity import SessionActivitySignal


def open_claims(
    holder: Any,
    session_id: str,
    *,
    permission: bool = False,
    notice: bool = False,
    at: Optional[datetime] = None,
) -> SessionActivitySignal:
    tracker = getattr(holder, "_activity_tracker", holder)
    signal = SessionActivitySignal(
        permission_open=permission,
        permission_opened_at=at if permission else None,
        notice_open=notice,
    )
    tracker._signals[session_id] = signal
    return signal
