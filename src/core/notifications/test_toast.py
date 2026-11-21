
from __future__ import annotations

from typing import Any, Optional

from src.core.notifications import agent_message, doc_model, sample_card
from src.core.notifications.sources import toast as toast_source
from src.models.notifications import Toast

TOAST_KIND = "Notification"
TARGETS = ("app", "desktop")


def live_session_id(manager: Any) -> Optional[str]:
    sessions = getattr(getattr(manager, "_registry", None), "sessions", None) or {}
    return next(iter(sessions), None)


def record(manager: Any, type_id: str, target: str, computer: str = "") -> Optional[Toast]:
    if target not in TARGETS:
        raise doc_model.SettingsValueError("bad target")
    session_id = live_session_id(manager)
    if session_id is None:
        return None
    hint = sample_card.sample_hint(type_id, computer)
    toast, _ = manager._toast_inbox.store(
        session_id, kind=TOAST_KIND, title=hint["title"], body=hint["body"], color=None, session_label=None,
        session_name=getattr(manager._registry.sessions[session_id], "tmux_session", None), notify_type=type_id)
    toast.test_target = target
    toast_source.remember_hint(toast.id, hint)
    return toast


async def broadcast(toast: Toast, app_state: Any) -> None:
    await agent_message._broadcast(toast, app_state=app_state)
