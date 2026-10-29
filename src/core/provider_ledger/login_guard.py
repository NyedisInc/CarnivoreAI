
from __future__ import annotations

from typing import Optional, Tuple

__all__ = ["live_login_session"]


def live_login_session(
    manager, account_id: str
) -> Optional[Tuple[str, Optional[str]]]:
    session_id = manager._sidecars.login_session_for(account_id)
    if session_id is None:
        return None
    registry = manager._registry
    session = registry.sessions.get(session_id)
    if session is None:
        return None
    backend = registry.backends.get(session_id)
    if backend is None or not backend.is_alive():
        return None
    return session_id, getattr(session, "tmux_session", None)
