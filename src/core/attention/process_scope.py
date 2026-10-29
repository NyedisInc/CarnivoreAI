
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from src.core.attention.evidence import Evidence
from src.core.attention.registry_record import REG_IDLE
from src.core.attention.transcript_facts import (
    FACTS_FOUND,
    FACTS_NO_RECORD,
    FACTS_UNREADABLE,
)

NEVER_PROMPTED_STATUS_SLACK_SECONDS: float = 2.0


def evidence_process_floor(
    session_started_epoch: Optional[int], restarted_at: Optional[datetime]
) -> Optional[datetime]:
    created = (
        datetime.fromtimestamp(int(session_started_epoch), tz=timezone.utc)
        if session_started_epoch is not None else None
    )
    measured = [at for at in (created, restarted_at) if at is not None]
    try:
        return max(measured) if measured else None
    except TypeError:
        return restarted_at


def transcript_predates_process(evidence: Evidence) -> bool:
    registry = evidence.registry
    facts = evidence.transcript
    starts = [
        at for at in (
            registry.started_at if registry.known else None,
            evidence.process_floor_at,
        ) if at is not None
    ]
    if not starts:
        return False
    if facts.verdict not in (FACTS_FOUND, FACTS_NO_RECORD):
        return False
    if facts.newest_append_at is None:
        return False
    try:
        return facts.newest_append_at < max(starts)
    except TypeError:
        return False


def never_prompted(evidence: Evidence) -> bool:
    registry = evidence.registry
    facts = evidence.transcript
    if not (registry.known and registry.status == REG_IDLE):
        return False
    if facts.verdict != FACTS_UNREADABLE or not facts.absent:
        return False
    if registry.started_at is None or registry.status_updated_at is None:
        return False
    try:
        changed = (registry.status_updated_at - registry.started_at).total_seconds()
    except TypeError:
        return False
    return changed <= NEVER_PROMPTED_STATUS_SLACK_SECONDS
