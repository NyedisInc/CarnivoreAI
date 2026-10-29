
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from src.api.subagent_listing import fresh_claude_observation
from src.core.attention.fresh_observation import watcher_of
from src.core.agent_families import DEFAULT_FAMILY
from src.core.timers.reader import iso
from src.core.timers.tally import NOT_APPLICABLE, TimerTally
from src.models import SessionInfo


def timer_tally_for(watcher: Any, info: Any, now: datetime) -> Optional[TimerTally]:
    family = getattr(info, "agent_family", None)
    if family is not None and family != DEFAULT_FAMILY:
        return NOT_APPLICABLE
    observation = fresh_claude_observation(watcher, info, now)
    if observation is None:
        return None
    return getattr(observation.evidence, "timers", None)


def mark_timers(session_manager: Any, infos: Iterable[Any]) -> None:
    watcher = watcher_of(session_manager)
    now = datetime.now(timezone.utc)
    for info in infos:
        if not isinstance(info, SessionInfo):
            continue
        tally = timer_tally_for(watcher, info, now)
        info.timers_state = tally.state if tally is not None else None
        info.timers_live = tally.live if tally is not None else None
        info.timers_next_fire_at = iso(tally.next_fire_at) if tally is not None else None
