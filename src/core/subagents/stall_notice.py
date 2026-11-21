
from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional, Sequence, Set, Tuple

import structlog

from src.core import session_change_notice
from src.core.attention.raise_gate import resolve_raise
from src.core.subagents.stall import StalledAgent
from src.models import ToastNewMessage

logger = structlog.get_logger(__name__)

TOAST_KIND: str = "Notification"

_StallKey = Tuple[str, str, str]


def stall_key(session_id: str, agent: StalledAgent) -> _StallKey:
    return (session_id, agent.agent_id, agent.last_activity_at.isoformat())


def notice_copy(agents: Sequence[StalledAgent]) -> Tuple[str, str]:
    minutes = max(1, min(agent.idle_seconds for agent in agents) // 60)
    if len(agents) == 1:
        label = agents[0].description or "a sub-agent"
        return ("a sub-agent looks stuck",
                f"{label} has written nothing for {minutes}m. nothing was stopped.")
    return (f"{len(agents)} sub-agents look stuck",
            f"{len(agents)} sub-agents have written nothing for {minutes}m or more. nothing was stopped.")


def make_stall_notice_raiser(
    manager: Any, app_state: Any, send: Callable[[str, str], None],
) -> Callable[[Any, Sequence[StalledAgent]], None]:
    announced: Dict[str, Set[_StallKey]] = {}

    def raise_notice(target: Any, stalled: Sequence[StalledAgent]) -> None:
        session_id = target.session_id
        present = {stall_key(session_id, agent): agent for agent in stalled}
        before = announced.get(session_id, set())
        fresh = [agent for key, agent in present.items() if key not in before]
        if present:
            announced[session_id] = set(present)
        else:
            announced.pop(session_id, None)
        if not fresh:
            return
        try:
            _raise(manager, app_state, send, session_id, fresh)
        except Exception as exc:  # noqa: BLE001
            logger.warning("subagent_stall_notice_failed", session_id=session_id,
                           error_type=type(exc).__name__)

    return raise_notice


def _raise(manager: Any, app_state: Any, send: Callable[[str, str], None],
           session_id: str, fresh: Sequence[StalledAgent]) -> Optional[str]:
    gate = resolve_raise(
        TOAST_KIND,
        policy_store_attached=getattr(manager, "_notification_policy_store", None) is not None,
        policy=manager.notification_policy_stamp(session_id))
    if not gate.raises_toast:
        logger.info(gate.log_event or "attention_toast_suppressed", session_id=session_id, **gate.log_fields)
        return None
    title, body = notice_copy(fresh)
    toast = manager.record_toast(session_id=session_id, kind=TOAST_KIND, title=title, body=body,
                                 notify_type="session.agent_stalled")
    payload = ToastNewMessage(toast=toast).model_dump_json()
    send(session_id, payload)
    session_change_notice.publish(app_state, json.loads(payload))
    return toast.id


__all__ = ["TOAST_KIND", "make_stall_notice_raiser", "notice_copy", "stall_key"]
