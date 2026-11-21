
from __future__ import annotations

import contextvars
import time
from collections import OrderedDict
from typing import Any, Mapping, Optional

import structlog

from src.core.notifications import contracts, types
from src.core.notifications.sources import common, open_checks
from src.core.swarm import watch
from src.core.session_activity import EVENT_NOTIFICATION, EVENT_PERMISSION_REQUEST, EVENT_STOP

logger = structlog.get_logger(__name__)

POSTED_IN_APP_ONLY = ("session.finished", "session.attention", "agent.message")


SELF_DELIVERED = ("swarm.question_climbed", "swarm.alert", "swarm.flash", "agent.update_ready")

_HINTS: "OrderedDict[str, Mapping[str, Any]]" = OrderedDict()
MAX_HINTS = 200


def remember_hint(toast_id: str, hint: Optional[Mapping[str, Any]]) -> None:
    if hint:
        _HINTS[toast_id] = hint
        _HINTS.move_to_end(toast_id)
        while len(_HINTS) > MAX_HINTS:
            _HINTS.popitem(last=False)


CARD_HINT: contextvars.ContextVar[Optional[Mapping[str, Any]]] = contextvars.ContextVar("notify_card_hint", default=None)


def attention_notify_type(kind: str, reason: Optional[str]) -> str:
    if kind == EVENT_STOP:
        return "session.finished"
    if kind == EVENT_NOTIFICATION:
        return "session.attention"
    if kind == EVENT_PERMISSION_REQUEST:
        if reason == "question":
            return "session.question"
        if reason == "plan_approval":
            return "session.plan_approval"
        return "session.permission"
    raise ValueError(f"no notification type for toast kind {kind!r}")


class UnknownNotificationTypeError(ValueError):
    pass


def event_notify_type(type_id: str) -> str:
    if not types.is_registered(type_id):
        raise UnknownNotificationTypeError(f"no registered notification type {type_id!r}")
    return type_id


def _is_swarm_body_in_app_only(manager: Any, toast: Any, type_id: str, tmux_name: Optional[str]) -> bool:
    if type_id not in POSTED_IN_APP_ONLY:
        return False
    try:
        epoch = (getattr(manager, "_instance_epochs", None) or {}).get(toast.session_id)
        return watch.agent_for_instance(tmux_name, epoch) is not None
    except (AttributeError, TypeError, ValueError):
        return False


def event_for_toast_id(manager: Any, toast_id: str) -> Optional[contracts.NotifyEvent]:
    toast = _find_toast(manager, toast_id)
    return build_event(manager, toast) if toast is not None else None


def _find_toast(manager: Any, toast_id: str) -> Any:
    from src.core import toast_history  # noqa: PLC0415

    return next((t for toasts in toast_history.buckets_from_inbox(manager._toast_inbox).values() for t in toasts if t.id == toast_id), None)


def test_target_for_toast_id(manager: Any, toast_id: str) -> Optional[str]:
    toast = _find_toast(manager, toast_id)
    return getattr(toast, "test_target", None) if toast is not None else None


def build_event(manager: Any, toast: Any, fields: Optional[dict] = None) -> Optional[contracts.NotifyEvent]:
    type_id = getattr(toast, "notify_type", None)
    if not type_id or not types.is_registered(type_id):
        return None
    fields = fields if fields is not None else common.session_fields(manager, toast.session_id)
    needs_you = type_id in types.NEEDS_YOU
    return contracts.NotifyEvent(
        type_id=type_id, kind=toast.kind, title=toast.title, ts=time.time(),
        severity=contracts.SEVERITY_WARN if needs_you else contracts.SEVERITY_INFO,
        instance_key=f"toast:{toast.id}:{toast.version}", toast_id=toast.id, toast_version=toast.version, details=toast.body,
        open_item=needs_you, card_hint=CARD_HINT.get() or _HINTS.get(toast.id), **{**fields, "session_ref": toast.session_label or fields.get("session_ref", "")},
    )


def emit_event(manager: Any, toast: Any) -> None:
    try:
        fields = common.session_fields(manager, toast.session_id)
        event = build_event(manager, toast, fields)
        if event is None or event.type_id in SELF_DELIVERED:
            return
        if _is_swarm_body_in_app_only(manager, toast, event.type_id, fields.get("tmux_name")):
            logger.debug("toast_notify_swarm_body_in_app_only", type_id=event.type_id)
            return
        if event.open_item:
            open_checks.remember_dialog(event.instance_key, getattr(manager, "_attention_watcher", None), toast.session_id)
        contracts.emit(event)
    except (AttributeError, TypeError, ValueError, OSError) as exc:
        logger.warning("toast_notify_emit_failed", error_type=type(exc).__name__)
