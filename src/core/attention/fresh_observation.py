
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional


def watcher_of(session_manager: Any) -> Optional[Any]:
    return getattr(session_manager, "_attention_watcher", None)


def fresh_observation(watcher: Optional[Any], row_id: str, now: datetime) -> Optional[Any]:
    if watcher is None:
        return None
    observation = watcher.observation_for(row_id, now=now)
    if observation is None or observation.stale:
        return None
    return observation
