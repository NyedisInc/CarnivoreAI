
from __future__ import annotations

from typing import Optional

from src.core.crosstalk import store
from src.core.mcp.common import ToolError

REPORT_BACK_SUFFIX = ('\n\nWhen the requested work is complete, report the actual outcome to your '
                      'parent with crosstalk_reply on this message. Include what changed, checks, and blockers.')
HEADER_ALLOWANCE_BYTES = 1024


def task_with_report_back(task: str, report_back: bool) -> str:
    return task + REPORT_BACK_SUFFIX if report_back else task


def validate_paste_text(task: str) -> None:
    from src.core.session_one_shot_gate import MAX_BODY_BYTES

    if len(task) > store.MAX_TEXT or len(task.encode('utf-8')) + HEADER_ALLOWANCE_BYTES > MAX_BODY_BYTES:
        raise ToolError('task exceeds the crosstalk delivery limit')
    if any((ord(char) < 32 and char not in '\n\t') or 127 <= ord(char) <= 159 for char in task):
        raise ToolError('task contains control characters the delivery guard would alter')


def agent_cli_flags(provider: str, effort: Optional[str], beast: bool) -> list[str]:
    flags: list[str] = []
    if effort:
        flags.extend(['-c', f'model_reasoning_effort="{effort}"'] if provider == 'codex' else ['--effort', effort])
    if beast and provider == 'codex':
        flags.append('--dangerously-bypass-approvals-and-sandbox')
    return flags
