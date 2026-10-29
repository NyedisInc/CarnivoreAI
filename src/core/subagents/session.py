
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.core.agent_families import DEFAULT_FAMILY
from src.core.session_token_usage import claude_reader
from src.core.session_token_usage.reader import SessionSubject
from src.core.session_transcript_presence import CONVERSATION_ABSENT, CONVERSATION_PRESENT
from src.core.subagents.contract import contract_versions
from src.core.subagents.reader import read_subagents
from src.models.subagents import SessionSubagents, SubagentCounts


def _zero_counts() -> SubagentCounts:
    return SubagentCounts(total=0, listed=0, running=0, done=0, unknown=0,
                          shape_unrecognized=0, internal=0)


def read_session_subagents(
    subject: SessionSubject,
    *,
    process_started_at: Optional[datetime] = None,
    projects_dir: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> SessionSubagents:
    instant = now or datetime.now(timezone.utc)
    stamp = instant.isoformat().replace("+00:00", "Z")
    family = subject.agent_family
    if family is not None and family != DEFAULT_FAMILY:
        return SessionSubagents(
            state="not_applicable", family=family, as_of=stamp,
            contract_versions=contract_versions(),
            detail="this agent family writes no subagent files",
        )
    base = dict(family=DEFAULT_FAMILY, conversation_uuid=subject.conversation_uuid,
                contract_versions=contract_versions(), as_of=stamp)
    if not subject.conversation_uuid:
        return SessionSubagents(state="absent", counts=_zero_counts(),
                                detail="this session has no conversation yet", **base)
    location = claude_reader.locate_transcript(
        subject.conversation_uuid, working_dir=subject.working_dir,
        projects_dir=projects_dir,
    )
    if location.outcome == CONVERSATION_ABSENT:
        return SessionSubagents(state="absent", counts=_zero_counts(),
                                detail="no transcript exists for this conversation yet",
                                **base)
    if location.outcome != CONVERSATION_PRESENT or location.path is None:
        return SessionSubagents(state="unchecked",
                                detail="the transcript corpus could not be read", **base)
    return read_subagents(location.path, conversation_uuid=subject.conversation_uuid,
                          process_started_at=process_started_at, now=instant)
