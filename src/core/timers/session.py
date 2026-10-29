
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.core.agent_families import DEFAULT_FAMILY
from src.core.attention.registry_record import REG_ABSENT, REG_OK, REG_STALE
from src.core.session_token_usage import claude_reader
from src.core.session_token_usage.reader import SessionSubject
from src.core.session_transcript_presence import CONVERSATION_ABSENT, CONVERSATION_PRESENT
from src.core.timers.contract import contract_versions
from src.core.timers.index import read_timer_index
from src.core.timers.reader import (
    PROCESS_ALIVE,
    PROCESS_GONE,
    PROCESS_UNKNOWN,
    UNKNOWN_PROCESS,
    ProcessFact,
    derive_timers,
    iso,
)
from src.models.timers import SessionTimers, TimerCounts


def process_fact_for(record: Any, conversation_uuid: Optional[str]) -> ProcessFact:
    if record is None or not conversation_uuid:
        return UNKNOWN_PROCESS
    verdict = getattr(record, "verdict", None)
    if verdict in (REG_ABSENT, REG_STALE):
        return ProcessFact(PROCESS_GONE)
    if verdict != REG_OK:
        return UNKNOWN_PROCESS
    if conversation_uuid not in (getattr(record, "session_uuid", None),
                                 getattr(record, "record_session_uuid", None)):
        return ProcessFact(PROCESS_GONE)
    started = getattr(record, "started_at", None)
    if started is None:
        return UNKNOWN_PROCESS
    return ProcessFact(PROCESS_ALIVE, started)


def _zero_counts() -> TimerCounts:
    return TimerCounts(total=0, live=0, fired=0, cancelled=0, superseded=0,
                       expired=0, lost=0, refused=0, unknown=0, shape_unrecognized=0)


def read_session_timers(
    subject: SessionSubject,
    process: ProcessFact,
    *,
    projects_dir: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> SessionTimers:
    instant = now or datetime.now(timezone.utc)
    base = dict(contract_versions=contract_versions(), as_of=iso(instant),
                process=process.state, process_started_at=iso(process.started_at))
    family = subject.agent_family
    if family is not None and family != DEFAULT_FAMILY:
        return SessionTimers(state="not_applicable", family=family,
                             detail="this agent family records no timer calls", **base)
    base.update(family=DEFAULT_FAMILY, conversation_uuid=subject.conversation_uuid)
    if not subject.conversation_uuid:
        return SessionTimers(state="absent", counts=_zero_counts(),
                             detail="this session has no conversation yet", **base)
    location = claude_reader.locate_transcript(
        subject.conversation_uuid, working_dir=subject.working_dir, projects_dir=projects_dir,
    )
    if location.outcome == CONVERSATION_ABSENT:
        return SessionTimers(state="absent", counts=_zero_counts(),
                             detail="no transcript exists for this conversation yet", **base)
    if location.outcome != CONVERSATION_PRESENT or location.path is None:
        return SessionTimers(state="unchecked",
                             detail="the transcript corpus could not be read", **base)
    index = read_timer_index(location.path)
    if index is None:
        return SessionTimers(state="unchecked",
                             detail="the transcript could not be read", **base)
    rows, counts, upcoming = derive_timers(index, process, instant)
    if process.state == PROCESS_UNKNOWN and counts.unknown > 0:
        return SessionTimers(
            state="unchecked", timers=rows,
            detail="the claude process holding this conversation could not be measured, "
                   "so whether its timers are live is not known", **base)
    return SessionTimers(state="ok", counts=counts, timers=rows,
                         next_fire_at=iso(upcoming), **base)
