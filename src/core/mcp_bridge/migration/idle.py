
from __future__ import annotations

from typing import Any, Optional

from src.core.auto_sleep import live_work
from src.core.hosts.identity import is_remote_info

FAMILY: str = "claude"
IDLE_STATUSES: frozenset = frozenset({"idle", "finished_unread"})
GATE_READY: str = "ready"
IDLE_SECONDS: float = 120.0

REASON_NOT_CLAUDE = "not_claude"
REASON_REMOTE = "remote"
REASON_NO_TMUX_NAME = "no_tmux_name"
REASON_STARTUP_GATE = "startup_gate"
REASON_SHELL_RUNNING = "shell_running"
REASON_NO_OBSERVATION = "no_observation"
REASON_LIVE_WORK = "live_work"
REASON_QUIET_UNMEASURED = "quiet_unmeasured"
REASON_NOT_QUIET = "not_quiet"
STATUS_PREFIX = "status_"


def _live_work(info: Any, observation: Any) -> bool:
    if getattr(info, "subagents_running", None) or getattr(info, "background_open", None):
        return True
    return live_work.hold_for(getattr(observation, "evidence", None), require_measured=True) is not None


def scope_refusal(info: Any) -> Optional[str]:
    if getattr(info, "agent_family", None) != FAMILY or getattr(info, "session", None) is None:
        return REASON_NOT_CLAUDE
    if is_remote_info(info):
        return REASON_REMOTE
    if not getattr(info, "tmux_session", None):
        return REASON_NO_TMUX_NAME
    return None


def refusal(info: Any, observation: Any, quiet_seconds: Optional[float]) -> Optional[str]:
    out_of_scope = scope_refusal(info)
    if out_of_scope is not None:
        return out_of_scope
    status = getattr(info, "activity_status", None)
    if status not in IDLE_STATUSES:
        return f"{STATUS_PREFIX}{status}"
    if getattr(info, "startup_gate", None) != GATE_READY:
        return REASON_STARTUP_GATE
    if getattr(info, "activity_hint", None) is not None:
        return REASON_SHELL_RUNNING
    if observation is None or getattr(observation, "stale", True):
        return REASON_NO_OBSERVATION
    if _live_work(info, observation):
        return REASON_LIVE_WORK
    if quiet_seconds is None:
        return REASON_QUIET_UNMEASURED
    if quiet_seconds < IDLE_SECONDS:
        return REASON_NOT_QUIET
    return None
