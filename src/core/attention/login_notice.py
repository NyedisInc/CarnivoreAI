
from __future__ import annotations

import json
from typing import Any, Callable, Optional, Set

import structlog

from src.core import session_change_notice
from src.core.attention.raise_gate import resolve_raise
from src.models import ToastNewMessage

logger = structlog.get_logger(__name__)

TOAST_KIND: str = "Notification"
NOTIFY_TYPE: str = "session.attention"
TITLE: str = "needs login"
BODY: str = "this session's claude login expired, so it answers every prompt with 'please run /login'. run /login in it."


def make_login_notice_raiser(
    manager: Any, app_state: Any, send: Callable[[str, str], None],
) -> Callable[[Any, Any], None]:
    told: Set[str] = set()

    def raise_notice(target: Any, observation: Any) -> None:
        session_id = target.session_id
        facts = getattr(getattr(observation, "evidence", None), "transcript", None)
        if facts is None:
            return
        if getattr(facts, "login_expired", None) is None:
            told.discard(session_id)
            return
        if session_id in told:
            return
        told.add(session_id)
        try:
            _raise(manager, app_state, send, session_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("login_expired_notice_failed", session_id=session_id, error_type=type(exc).__name__)

    return raise_notice


def _raise(manager: Any, app_state: Any, send: Callable[[str, str], None], session_id: str) -> Optional[str]:
    gate = resolve_raise(
        TOAST_KIND,
        policy_store_attached=getattr(manager, "_notification_policy_store", None) is not None,
        policy=manager.notification_policy_stamp(session_id))
    if not gate.raises_toast:
        logger.info(gate.log_event or "attention_toast_suppressed", session_id=session_id, **gate.log_fields)
        return None
    toast = manager.record_toast(session_id=session_id, kind=TOAST_KIND, title=TITLE, body=BODY,
                                 notify_type="session.attention")
    payload = ToastNewMessage(toast=toast).model_dump_json()
    send(session_id, payload)
    session_change_notice.publish(app_state, json.loads(payload))
    logger.info("login_expired_notified", session_id=session_id)
    return toast.id


__all__ = ["NOTIFY_TYPE", "TOAST_KIND", "make_login_notice_raiser"]
