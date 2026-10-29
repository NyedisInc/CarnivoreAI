
from __future__ import annotations

from typing import Dict, Optional

import structlog

logger = structlog.get_logger()


class AttachmentSidecars:

    def __init__(self) -> None:
        self.adopt_fifo_offsets: Dict[str, int] = {}
        self.pending_logins: Dict[str, str] = {}
        self.device_logins: set[str] = set()
        self.login_sessions: Dict[str, str] = {}


    def set_fifo_offset(self, session_id: str, offset: int) -> None:
        self.adopt_fifo_offsets[session_id] = offset

    def peek_fifo_offset(self, session_id: str) -> Optional[int]:
        return self.adopt_fifo_offsets.get(session_id)

    def take_fifo_offset(self, session_id: str) -> Optional[int]:
        return self.adopt_fifo_offsets.pop(session_id, None)


    def set_pending_login(
        self, session_id: str, account_id: str, device_auth: bool = False
    ) -> None:
        self.pending_logins[session_id] = account_id
        if device_auth:
            self.device_logins.add(session_id)
        self.login_sessions[account_id] = session_id

    def take_pending_login(self, session_id: str) -> Optional[str]:
        return self.pending_logins.pop(session_id, None)

    def take_pending_login_device(self, session_id: str) -> bool:
        found = session_id in self.device_logins
        self.device_logins.discard(session_id)
        return found

    def login_session_for(self, account_id: str) -> Optional[str]:
        return self.login_sessions.get(account_id)


    def forget(self, session_id: str) -> None:
        self.adopt_fifo_offsets.pop(session_id, None)
        self.pending_logins.pop(session_id, None)
        self.device_logins.discard(session_id)
        for account_id, owner in list(self.login_sessions.items()):
            if owner == session_id:
                del self.login_sessions[account_id]
