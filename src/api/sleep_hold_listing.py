
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from src.core.auto_sleep.live_work import hold_for
from src.core.auto_sleep.sleeper import is_sleepable_agent
from src.models import SessionInfo
from src.models.auto_sleep import SleepHoldInfo


def sleep_hold_for(watcher: Any, info: Any, now: datetime) -> Optional[SleepHoldInfo]:
    session = getattr(info, "session", None)
    if watcher is None or session is None or not is_sleepable_agent(info):
        return None
    observation = watcher.observation_for(session.id, now=now)
    if observation is None or observation.stale:
        return None
    hold = hold_for(observation.evidence, require_measured=False)
    return SleepHoldInfo(reasons=list(hold.reasons), text=hold.text) if hold else None


def mark_sleep_hold(session_manager: Any, infos: Iterable[Any], sleeper: Any = None) -> None:
    watcher = getattr(session_manager, "_attention_watcher", None)
    now = datetime.now(timezone.utc)
    for info in infos:
        if isinstance(info, SessionInfo):
            info.sleep_hold = sleep_hold_for(watcher, info, now)
            session = info.session
            info.sleep_verdict = (
                sleeper.verdict_for(session.id)
                if sleeper is not None and session is not None and is_sleepable_agent(info) else None)
