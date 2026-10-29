
from __future__ import annotations

from typing import Dict, Optional

from src.core.attention.evidence import (
    REASON_INPUT,
    REASON_PANE_DEAD,
    REASON_PERMISSION,
    REASON_PLAN_APPROVAL,
    REASON_QUESTION,
    REASON_QUEUED_REINVOKE,
    REASON_STREAMING,
    REASON_SUBAGENTS,
    REASON_TOOL,
    STATE_BUSY,
    STATE_DONE_IDLE,
    STATE_NEEDS_USER,
    TIER_NONE,
    TIER_PANE,
    TIER_REGISTRY,
    TIER_TMUX,
    TIER_TRANSCRIPT,
    AttentionVerdict,
)
from src.core.attention.registry_read import REG_SHELL, RegistryRecord
from src.core.session_status import (
    STATUS_DEAD,
    STATUS_IDLE,
    STATUS_NOTICE,
    STATUS_QUESTION,
    STATUS_UNKNOWN,
    STATUS_WORKING,
    STATUS_WORKING_SUBAGENT,
    derive_read_state,
)
from src.core.session_status_source import (
    STATUS_SOURCE_NONE,
    STATUS_SOURCE_PANE,
    STATUS_SOURCE_REGISTRY,
    STATUS_SOURCE_TMUX,
    STATUS_SOURCE_TRANSCRIPT,
)

_NEEDS_USER_STATUS: Dict[str, str] = {
    REASON_QUESTION: STATUS_QUESTION,
    REASON_PERMISSION: STATUS_QUESTION,
    REASON_PLAN_APPROVAL: STATUS_QUESTION,
    REASON_INPUT: STATUS_NOTICE,
}

_BUSY_STATUS: Dict[str, str] = {
    REASON_SUBAGENTS: STATUS_WORKING_SUBAGENT,
    REASON_QUEUED_REINVOKE: STATUS_WORKING_SUBAGENT,
    REASON_STREAMING: STATUS_WORKING,
    REASON_TOOL: STATUS_WORKING,
}

ACTIVITY_HINT_SHELL: str = "shell"

_REGISTRY_HINTS: Dict[str, str] = {REG_SHELL: ACTIVITY_HINT_SHELL}

_TIER_SOURCES: Dict[str, str] = {
    TIER_REGISTRY: STATUS_SOURCE_REGISTRY,
    TIER_TRANSCRIPT: STATUS_SOURCE_TRANSCRIPT,
    TIER_PANE: STATUS_SOURCE_PANE,
    TIER_TMUX: STATUS_SOURCE_TMUX,
    TIER_NONE: STATUS_SOURCE_NONE,
}


def to_display(
    verdict: AttentionVerdict, *, unread: bool, tmux_status: str
) -> str:
    if verdict.state == STATE_DONE_IDLE:
        return derive_read_state(STATUS_IDLE, unread=unread)
    if verdict.state == STATE_NEEDS_USER:
        return _NEEDS_USER_STATUS.get(verdict.reason, STATUS_QUESTION)
    if verdict.state == STATE_BUSY:
        return _BUSY_STATUS.get(verdict.reason, STATUS_WORKING)
    if verdict.reason == REASON_PANE_DEAD or tmux_status == STATUS_DEAD:
        return STATUS_DEAD
    return STATUS_UNKNOWN


def status_source_for(verdict: AttentionVerdict) -> str:
    return _TIER_SOURCES.get(verdict.tier, STATUS_SOURCE_NONE)


def activity_hint_for(registry: RegistryRecord) -> Optional[str]:
    if not registry.known:
        return None
    return _REGISTRY_HINTS.get(registry.status or "")
