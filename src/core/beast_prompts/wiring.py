
from __future__ import annotations

from typing import Any, Callable

import structlog

from src.core.approvals import beast_grid
from src.core.approvals.extract import FAMILY_CLAUDE, FAMILY_CODEX, Dialog
from src.core.approvals.plain_answer import summarize, summary_line
from src.core.beast_prompts.engine import HISTORY_ACTION, NOTIFY_TYPE, BeastPromptsEngine
from src.core.mcp import beast_mode, beast_store, pending
from src.core.notifications import contracts
from src.core.notifications.sources import common

logger = structlog.get_logger()


def record_and_announce(get_manager: Callable[[], Any]) -> Callable[[Any, Dialog], None]:

    def on_answered(info: Any, dialog: Dialog) -> None:
        session_id, tmux = info.session.id, info.tmux_session or ""
        tool, command = summarize(dialog)
        line = summary_line(dialog) or dialog.kind
        try:
            pending.get_store().record_beast(
                caller_session_id=session_id, caller_tmux=tmux, external_client="", target_session_id=session_id,
                target_tmux=tmux, action=HISTORY_ACTION, args_summary=line,
                args={"kind": dialog.kind, "tool": tool, "command": command},
                result={"status": "answered", "choice": "yes"},
            )
        except (OSError, ValueError) as exc:
            logger.warning("beast_prompt_history_unwritable", session_id=session_id, error_type=type(exc).__name__)
        event = contracts.NotifyEvent(
            type_id=NOTIFY_TYPE, kind="beast_prompt", title=common.type_title(NOTIFY_TYPE), ts=common.now(),
            instance_key=f"beast_prompt:{session_id}:{dialog.fingerprint[:16]}", details=line,
            **common.session_fields(get_manager(), session_id),
        )
        contracts.emit(event)

    return on_answered


PROMPT_ROWS = {FAMILY_CLAUDE: beast_grid.ROW_CLAUDE_PERMISSION, FAMILY_CODEX: beast_grid.ROW_CODEX_APPROVAL}


def prompt_allowed(dialog: Dialog) -> bool:
    row = PROMPT_ROWS.get(dialog.family)
    return row is not None and beast_mode.handles(row)


def build_engine(get_manager: Callable[[], Any], get_watcher: Callable[[], Any]) -> BeastPromptsEngine:
    return BeastPromptsEngine(get_manager, get_watcher, enabled=prompt_allowed,
                              on_answered=record_and_announce(get_manager),
                              on_expiry=beast_store.disarm_if_expired, expired=beast_mode.armed_but_expired)
