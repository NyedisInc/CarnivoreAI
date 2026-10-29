
from __future__ import annotations

from typing import Optional

from src.core.attention.evidence import (
    REASON_PERMISSION,
    REASON_PLAN_APPROVAL,
    REASON_QUESTION,
)
from src.core.attention.toast_facts import TARGET_CHARS, ToastFacts
from src.models.notifications import ToastDetail

_TOOL_REASONS = frozenset({REASON_PERMISSION, REASON_QUESTION, REASON_PLAN_APPROVAL})

_ASKING_TOOLS = frozenset({"AskUserQuestion", "ExitPlanMode"})


def detail_for(reason: Optional[str], facts: Optional[ToastFacts]) -> ToastDetail:
    if facts is None:
        return ToastDetail(reason=reason)
    about_tool = reason in _TOOL_REASONS and facts.pending_tool is not None
    tool = facts.pending_tool if about_tool else None
    target = facts.pending_target if about_tool else None
    snippet = facts.last_text
    if about_tool and tool in _ASKING_TOOLS and target:
        snippet = target
        target = None
    title_target = target
    if title_target is not None and len(title_target) > TARGET_CHARS:
        title_target = title_target[: TARGET_CHARS - 3].rstrip() + "..."
    return ToastDetail(reason=reason, tool=tool, target=title_target, snippet=snippet)
