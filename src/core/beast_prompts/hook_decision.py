
from __future__ import annotations

from typing import Any, Dict

import structlog

from src.core.approvals import beast_grid
from src.core.beast_prompts.engine import HISTORY_ACTION
from src.core.mcp import beast_mode, pending
from src.core.timers.redact import redact

logger = structlog.get_logger()

OWNER_ONLY_TOOLS = frozenset({"AskUserQuestion", "ExitPlanMode"})
_DETAIL_KEYS = ("command", "file_path", "path", "url", "pattern")


def allowed(tool_name: str) -> bool:
    if not tool_name or tool_name in OWNER_ONLY_TOOLS:
        return False
    return beast_mode.handles(beast_grid.ROW_CLAUDE_PERMISSION)


def summary(tool_name: str, tool_input: Dict[str, Any]) -> str:
    detail = next((str(tool_input[k]) for k in _DETAIL_KEYS if tool_input.get(k)), "")
    detail = " ".join(redact(detail).split())
    detail = detail if len(detail) <= 120 else detail[:117] + "..."
    return f"{tool_name}: {detail}" if detail else tool_name


def record(session_id: str, tmux: str, tool_name: str, tool_input: Dict[str, Any]) -> None:
    try:
        pending.get_store().record_beast(
            caller_session_id=session_id, caller_tmux=tmux, external_client="", target_session_id=session_id, target_tmux=tmux,
            action=HISTORY_ACTION, args_summary=summary(tool_name, tool_input),
            args={"kind": "permission", "tool": tool_name, "command": summary(tool_name, tool_input).partition(": ")[2], "via": "hook"},
            result={"status": "answered", "choice": "yes"})
    except (OSError, ValueError) as exc:
        logger.warning("beast_hook_history_unwritable", session_id=session_id, error_type=type(exc).__name__)
