
from __future__ import annotations

from typing import Any, Callable

import structlog

from src.core.approvals.extract import Dialog
from src.core.mcp import pending
from src.core.notifications import contracts
from src.core.notifications.sources import common

logger = structlog.get_logger()

HISTORY_ACTION = "startup_screen"
NOTIFY_TYPE = "session.auto_accepted"
SOURCE_PREFIX = "auto answered by rule "

OnPressed = Callable[[Any, Dialog, str, str, str], None]


def record_and_announce(get_manager: Callable[[], Any]) -> OnPressed:

    def on_pressed(info: Any, dialog: Dialog, rule_id: str, label: str, evidence: str) -> None:
        session_id, tmux = info.session.id, info.tmux_session or ""
        line = f"{rule_id}: {label}"
        try:
            pending.get_store().record_beast(
                caller_session_id=session_id, caller_tmux=tmux, external_client="", target_session_id=session_id, target_tmux=tmux,
                action=HISTORY_ACTION, args_summary=line,
                args={"rule": rule_id, "screen": dialog.startup_kind or dialog.kind, "evidence": evidence},
                result={"status": "answered", "choice": label}, approval_source=SOURCE_PREFIX + rule_id)
        except (OSError, ValueError) as exc:
            logger.warning("auto_answer_history_unwritable", session_id=session_id, rule=rule_id, error_type=type(exc).__name__)
        try:
            contracts.emit(contracts.NotifyEvent(
                type_id=NOTIFY_TYPE, kind="auto_accepted", title=common.type_title(NOTIFY_TYPE), ts=common.now(),
                instance_key=f"auto_accepted:{session_id}:{rule_id}:{dialog.fingerprint[:16]}", details=line,
                **common.session_fields(get_manager(), session_id)))
        except (OSError, ValueError, KeyError) as exc:
            logger.warning("auto_answer_notice_failed", session_id=session_id, rule=rule_id, error_type=type(exc).__name__)

    return on_pressed
