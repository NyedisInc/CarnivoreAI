
from __future__ import annotations

import time
from typing import Any, Optional

import structlog

from src.core.notifications import contracts, types
from src.core.notifications.sources import common, open_checks
from src.core.swarm import watch
from src.core.session_activity import EVENT_NOTIFICATION, EVENT_PERMISSION_REQUEST, EVENT_STOP

logger = structlog.get_logger(__name__)

POSTED_IN_APP_ONLY = ("session.finished", "session.attention", "session.posted")


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


def _is_swarm_body_in_app_only(manager: Any, toast: Any, type_id: str, tmux_name: Optional[str]) -> bool:
    if type_id not in POSTED_IN_APP_ONLY:
        return False
    try:
        epoch = (getattr(manager, "_instance_epochs", None) or {}).get(toast.session_id)
        return watch.agent_for_instance(tmux_name, epoch) is not None
    except (AttributeError, TypeError, ValueError):
        return False


def emit_event(manager: Any, toast: Any) -> None:
    type_id = getattr(toast, "notify_type", None)
    if not type_id or not types.is_registered(type_id):
        return
    try:
        key = f"toast:{toast.id}:{toast.version}"
        fields = common.session_fields(manager, toast.session_id)
        if _is_swarm_body_in_app_only(manager, toast, type_id, fields.get("tmux_name")):
            logger.debug("toast_notify_swarm_body_in_app_only", type_id=type_id)
            return
        needs_you = type_id in types.NEEDS_YOU
        if needs_you:
            open_checks.remember_dialog(key, getattr(manager, "_attention_watcher", None), toast.session_id)
        contracts.emit(contracts.NotifyEvent(
            type_id=type_id, kind=toast.kind, title=toast.title, ts=time.time(),
            severity=contracts.SEVERITY_WARN if needs_you else contracts.SEVERITY_INFO,
            instance_key=key, toast_id=toast.id, toast_version=toast.version, details=toast.body,
            open_item=needs_you, **{**fields, "session_ref": toast.session_label or fields.get("session_ref", "")},
        ))
    except (AttributeError, TypeError, ValueError, OSError) as exc:
        logger.warning("toast_notify_emit_failed", error_type=type(exc).__name__)
