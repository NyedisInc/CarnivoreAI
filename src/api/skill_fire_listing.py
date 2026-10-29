
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from src.core.agent_families import DEFAULT_FAMILY
from src.core.skill_fires.tally import UNSUPPORTED, SkillTally
from src.models import SessionInfo
from src.models.sessions import SkillLast


def skill_tally_for(watcher: Any, info: Any, now: datetime) -> Optional[SkillTally]:
    family = getattr(info, "agent_family", None)
    if family is not None and family not in (DEFAULT_FAMILY, "codex"):
        return UNSUPPORTED
    session = getattr(info, "session", None)
    if watcher is None or session is None:
        return None
    observation = watcher.observation_for(session.id, now=now)
    if observation is None or observation.stale:
        return None
    return getattr(observation.evidence, "skills", None)


def mark_skill_fires(session_manager: Any, infos: Iterable[Any]) -> None:
    watcher = getattr(session_manager, "_attention_watcher", None)
    now = datetime.now(timezone.utc)
    for info in infos:
        if not isinstance(info, SessionInfo):
            continue
        tally = skill_tally_for(watcher, info, now)
        info.skills_state = tally.state if tally is not None else None
        info.skills_fired = tally.fired if tally is not None else None
        info.skill_last = (SkillLast(name=tally.last_skill, at=tally.last_at)
                           if tally is not None and tally.last_skill else None)
