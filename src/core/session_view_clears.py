
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog

from src.core.attention.evidence import STATE_DONE_IDLE
from src.core.sessions.ports import SessionManagerSurface

logger = structlog.get_logger(__name__)


def session_ids_for_tmux_name(manager: SessionManagerSurface, tmux_name: str) -> list[str]:
    if not tmux_name:
        return []
    from src.core.hosts.identity import instance_name

    backends = manager._registry.backends
    return [
        sid
        for sid, backend in backends.items()
        if instance_name(backend) == tmux_name
    ]


def clear_view_state(
    manager: SessionManagerSurface,
    *,
    session_id: Optional[str] = None,
    tmux_name: Optional[str] = None,
) -> bool:
    ids: list[str] = []
    if session_id:
        ids.append(session_id)

    if not tmux_name and session_id:
        from src.core.hosts.identity import instance_name

        tmux_name = instance_name(manager._registry.get_backend(session_id))

    if tmux_name:
        for sid in session_ids_for_tmux_name(manager, tmux_name):
            if sid not in ids:
                ids.append(sid)

    if not tmux_name:
        return False

    store = manager._unread_store
    if store is None:
        return False
    from src.core import unread_follow_up

    unread_follow_up.clear(manager, tmux_name)
    logger.debug("session_view_cleared", tmux_name=tmux_name, ids=len(ids))
    return True


def view_marks_read(manager: SessionManagerSurface, session_id: str) -> bool:
    watcher = manager._attention_watcher
    if watcher is None or not session_id:
        return True
    observation = watcher.observation_for(
        session_id, now=datetime.now(timezone.utc)
    )
    if observation is None:
        return True
    return observation.verdict.state == STATE_DONE_IDLE


def clear_on_view(manager: SessionManagerSurface, session_id: str) -> bool:
    if not view_marks_read(manager, session_id):
        logger.debug("session_view_clear_deferred_not_at_rest",
                     session_id=session_id)
        return False
    return clear_view_state(manager, session_id=session_id)
