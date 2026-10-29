
from __future__ import annotations

from collections import OrderedDict
from typing import Any, Callable, Optional

from src.core.attention.evidence import REASON_INPUT, REASON_PERMISSION, REASON_PLAN_APPROVAL, REASON_QUESTION
from src.core.notifications import contracts

_REASONS = {
    "session.permission": frozenset({REASON_PERMISSION}),
    "session.question": frozenset({REASON_QUESTION}),
    "session.plan_approval": frozenset({REASON_PLAN_APPROVAL}),
    "session.attention": frozenset({REASON_INPUT, REASON_PERMISSION, REASON_QUESTION, REASON_PLAN_APPROVAL}),
}

_FINGERPRINTS: "OrderedDict[str, str]" = OrderedDict()
_FINGERPRINT_CAP = 512


def _dialog_of(watcher: Any, session_id: Optional[str]) -> Any:
    observation = watcher.observation_for(session_id) if watcher is not None and session_id else None
    return getattr(getattr(observation, "evidence", None), "dialog", None)


def remember_dialog(instance_key: str, watcher: Any, session_id: Optional[str]) -> None:
    dialog = _dialog_of(watcher, session_id)
    if dialog is None:
        return
    _FINGERPRINTS[instance_key] = dialog.fingerprint
    while len(_FINGERPRINTS) > _FINGERPRINT_CAP:
        _FINGERPRINTS.popitem(last=False)


def session_still_waiting(watcher: Any, event: contracts.NotifyEvent) -> bool:
    observation = watcher.observation_for(event.session_id) if watcher is not None and event.session_id else None
    if observation is None or observation.verdict.reason not in _REASONS.get(event.type_id, frozenset()):
        return False
    seen = _FINGERPRINTS.get(event.instance_key)
    dialog = _dialog_of(watcher, event.session_id)
    return seen is None or (dialog is not None and dialog.fingerprint == seen)


def register_open_checks(engine: Any, get_watcher: Callable[[], Any], get_pending_store: Callable[[], Any]) -> None:
    for type_id in _REASONS:
        engine.register_open_check(type_id, lambda event: session_still_waiting(get_watcher(), event))

    def agent_action_open(event: contracts.NotifyEvent) -> bool:
        return any(row.get("id") == event.instance_key for row in get_pending_store().list())

    engine.register_open_check("approval.agent_action", agent_action_open)
