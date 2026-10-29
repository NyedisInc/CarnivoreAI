
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from src.api.subagent_listing import _fresh_claude_observation
from src.core.attention.background_claims import (
    measurement_overrules_claims, standing_background_claims,
)
from src.core.attention.transcript_facts import FACTS_FOUND
from src.core.attention.usage_limit import active_usage_limit
from src.core.subagents.parked_work import describe_entry
from src.models import SessionInfo
from src.models.sessions import BackgroundProcessesInfo, UsageLimitInfo


def _open_background_summary(evidence: Any) -> Optional[str]:
    count = standing_background_claims(evidence)
    if count <= 0:
        return None
    noun = "shell or monitor" if count == 1 else "shells or monitors"
    return "%d background %s started by this session, still running" % (count, noun)


def parked_summary_for(watcher: Any, info: Any, now: datetime) -> Optional[str]:
    observation = _fresh_claude_observation(watcher, info, now)
    if observation is None:
        return None
    evidence = observation.evidence
    parked = getattr(evidence, "parked_work", None)
    if parked is not None and getattr(parked, "is_live", False) and parked.entries:
        return describe_entry(parked.entries[0], now=now)
    return _open_background_summary(evidence)


def mark_parked_work(session_manager: Any, infos: Iterable[Any]) -> None:
    watcher = getattr(session_manager, "_attention_watcher", None)
    now = datetime.now(timezone.utc)
    for info in infos:
        if not isinstance(info, SessionInfo):
            continue
        info.parked_summary = parked_summary_for(watcher, info, now)
        info.background_open = background_open_for(watcher, info, now)
        info.background_processes = background_processes_for(watcher, info, now)
        info.usage_limit = usage_limit_for(watcher, info, now)


def background_open_for(watcher: Any, info: Any, now: datetime) -> Optional[int]:
    observation = _fresh_claude_observation(watcher, info, now)
    if observation is None:
        return None
    evidence = observation.evidence
    if measurement_overrules_claims(evidence):
        return 0
    measured = getattr(evidence, "background_open", None)
    if measured is not None:
        return int(measured)
    facts = getattr(evidence, "transcript", None)
    if facts is None or getattr(facts, "verdict", None) != FACTS_FOUND:
        return None
    parked = getattr(evidence, "parked_work", None)
    live_parked = sum(1 for entry in getattr(parked, "entries", ()) or () if entry.live)
    return standing_background_claims(evidence) + live_parked


def usage_limit_for(watcher: Any, info: Any, now: datetime) -> Optional[UsageLimitInfo]:
    session = getattr(info, "session", None)
    if watcher is None or session is None:
        return None
    observation = watcher.observation_for(session.id, now=now)
    if observation is None or observation.stale:
        return None
    codex = getattr(observation.evidence, "codex", None)
    facts = codex.transcript if codex is not None else getattr(observation.evidence, "transcript", None)
    limit = active_usage_limit(getattr(facts, "usage_limit", None), now)
    if limit is None:
        return None
    return UsageLimitInfo(
        kind=limit.kind,
        resets_at=limit.resets_at.isoformat() if limit.resets_at else None,
        message=limit.message,
        since=limit.since.isoformat() if limit.since else None,
    )


def background_processes_for(watcher: Any, info: Any, now: datetime) -> Optional[BackgroundProcessesInfo]:
    observation = _fresh_claude_observation(watcher, info, now)
    if observation is None:
        return None
    measure = getattr(observation.evidence, "background_process", None)
    if measure is None:
        return None
    return BackgroundProcessesInfo(state=measure.state, count=measure.count)
