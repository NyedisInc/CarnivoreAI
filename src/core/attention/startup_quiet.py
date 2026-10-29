
from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional, Set

STARTUP_QUIET_WINDOW_SECONDS: float = 180.0


class StartupQuiet:

    def __init__(self) -> None:
        self._armed_at: Dict[str, datetime] = {}

    def arm(self, session_id: str, now: datetime) -> None:
        self._armed_at[session_id] = now

    def is_armed(self, session_id: str) -> bool:
        return session_id in self._armed_at

    def end(self, session_id: str) -> None:
        self._armed_at.pop(session_id, None)

    def retain_only(self, live_session_ids: Set[str], now: datetime) -> None:
        for session_id, armed_at in list(self._armed_at.items()):
            if session_id in live_session_ids:
                continue
            try:
                expired = (now - armed_at).total_seconds() > STARTUP_QUIET_WINDOW_SECONDS
            except TypeError:
                expired = True
            if expired:
                del self._armed_at[session_id]

    def swallows_done(self, session_id: str, now: datetime) -> bool:
        armed_at: Optional[datetime] = self._armed_at.pop(session_id, None)
        if armed_at is None:
            return False
        try:
            return (now - armed_at).total_seconds() <= STARTUP_QUIET_WINDOW_SECONDS
        except TypeError:
            return False
