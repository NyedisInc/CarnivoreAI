
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from src.api.subagent_listing import _fresh_claude_observation
from src.core.hosts.identity import is_remote_info
from src.core.mcp_health.agent_process import FAMILY_CLAUDE, FAMILY_CODEX
from src.core.mcp_health.monitor import Target

MEASURED_FAMILIES = frozenset({FAMILY_CLAUDE, FAMILY_CODEX})


def tmux_name(info: Any) -> Optional[str]:
    return getattr(info, "tmux_session", None) or getattr(info.session, "tmux_session", None)


def monitor_target(watcher: Any, info: Any, now: datetime) -> Optional[Target]:
    family = getattr(info, "agent_family", None)
    name = tmux_name(info)
    if family not in MEASURED_FAMILIES or not name or is_remote_info(info):
        return None
    if getattr(info, "activity_status", None) == "dead":
        return None
    session = info.session
    registry = None
    if family == FAMILY_CLAUDE:
        observation = _fresh_claude_observation(watcher, info, now)
        registry = getattr(observation.evidence, "registry", None) if observation is not None else None
    known = registry is not None and getattr(registry, "known", False)
    return Target(
        session_id=str(session.id), tmux_name=name, family=family,
        epoch=getattr(session, "tmux_created_epoch", None), pane_pid=getattr(session, "pty_pid", None),
        agent_pid=getattr(registry, "pid", None) if known else None,
        agent_started_at=getattr(registry, "started_at", None) if known else None,
        agent_cwd=getattr(registry, "cwd", None) if known else None,
        working_dir=getattr(session, "working_dir", None),
    )
