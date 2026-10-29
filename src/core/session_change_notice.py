
from __future__ import annotations

from typing import Any, Dict, Optional

import structlog

from src.core.event_hub import EventHub, get_hub
from src.core.ttl_flight import invalidate_all
from src.models import WSMessageType

logger = structlog.get_logger()


def build_status_notice(
    *,
    session_id: str,
    tmux_session: Optional[str] = None,
    epoch: Optional[int] = None,
    activity_status: Optional[str] = None,
    unread: Optional[bool] = None,
    startup_gate: Optional[str] = None,
) -> Dict[str, Any]:
    frame: Dict[str, Any] = {
        "type": WSMessageType.SESSION_STATUS_CHANGED,
        "session_id": session_id,
    }
    if tmux_session:
        frame["tmux_session"] = tmux_session
    if epoch is not None:
        frame["epoch"] = epoch
    if activity_status is not None:
        frame["activity_status"] = activity_status
    if unread is not None:
        frame["unread"] = unread
    if startup_gate is not None:
        frame["startup_gate"] = startup_gate
    return frame


def build_structural_notice(reason: str) -> Dict[str, Any]:
    return {"type": WSMessageType.SESSIONS_CHANGED, "reason": reason}


def build_rename_notice(*, session_id: str, new_name: str) -> Dict[str, Any]:
    return {
        "type": WSMessageType.SESSION_RENAMED,
        "session_id": session_id,
        "new_name": new_name,
    }


def publish(app_state: Any, frame: Dict[str, Any]) -> int:
    invalidate_all()
    hub: Optional[EventHub] = get_hub(app_state)
    if hub is None:
        return 0
    return hub.publish(frame)


def publish_attention_status(
    app_state: Any,
    session_manager: Any,
    session_id: str,
    *,
    activity_status: Optional[str] = None,
) -> int:
    invalidate_all()
    hub = get_hub(app_state)
    if hub is None or hub.client_count == 0:
        return 0

    unread: Optional[bool] = None
    tmux_session: Optional[str] = None
    epoch: Optional[int] = None

    registry = getattr(getattr(app_state, "services", None), "registry", None)
    backend = None
    getter = getattr(registry, "get_backend", None)
    if callable(getter):
        backend = getter(session_id)
    tmux_session = getattr(backend, "tmux_session", None)
    if tmux_session is None:
        authority = getattr(session_manager, "hook_tokens", None)
        tmux_session = (getattr(authority, "tmux_names", None) or {}).get(session_id)
    epoch = getattr(session_manager, "_instance_epochs", {}).get(session_id)

    if tmux_session:
        reader = getattr(session_manager, "_is_unread", None)
        if callable(reader):
            try:
                unread = bool(reader(tmux_session, epoch))
            except OSError as exc:
                logger.debug("event_notice_unread_unreadable",
                             session_id=session_id, error=str(exc))

    if activity_status is not None:
        from src.core.session_status import derive_read_state

        activity_status = derive_read_state(
            activity_status, unread=bool(unread)
        )

    return hub.publish(
        build_status_notice(
            session_id=session_id,
            tmux_session=tmux_session,
            epoch=epoch,
            activity_status=activity_status,
            unread=unread,
        )
    )
