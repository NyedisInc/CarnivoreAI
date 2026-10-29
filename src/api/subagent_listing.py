
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from src.core.agent_families import DEFAULT_FAMILY
from src.core.attention.workflow_activity import workflow_active
from src.core.subagents.tally import NOT_APPLICABLE, SubagentTally
from src.models import SessionInfo


def _fresh_claude_observation(watcher: Any, info: Any, now: datetime) -> Any:
    family = getattr(info, "agent_family", None)
    if family is not None and family != DEFAULT_FAMILY:
        return None
    session = getattr(info, "session", None)
    if watcher is None or session is None:
        return None
    observation = watcher.observation_for(session.id, now=now)
    if observation is None or observation.stale:
        return None
    return observation


def _tally_from(info: Any, observation: Any) -> Optional[SubagentTally]:
    family = getattr(info, "agent_family", None)
    if family is not None and family != DEFAULT_FAMILY:
        return NOT_APPLICABLE
    if observation is None:
        return None
    return getattr(observation.evidence, "subagents", None)


def tally_for(watcher: Any, info: Any, now: datetime) -> Optional[SubagentTally]:
    return _tally_from(info, _fresh_claude_observation(watcher, info, now))


def mark_subagents(session_manager: Any, infos: Iterable[Any]) -> None:
    watcher = getattr(session_manager, "_attention_watcher", None)
    now = datetime.now(timezone.utc)
    for info in infos:
        if not isinstance(info, SessionInfo):
            continue
        observation = _fresh_claude_observation(watcher, info, now)
        tally = _tally_from(info, observation)
        info.subagents_state = tally.state if tally is not None else None
        info.subagents_running = tally.running if tally is not None else None
        info.subagents_total = tally.total if tally is not None else None
        info.workflow_active = (
            workflow_active(observation.evidence) if observation is not None else None
        )
