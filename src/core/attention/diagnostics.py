
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel


class ObservationDiagnostic(BaseModel):
    """Safe status metadata for one session: no terminal or transcript text.

    Fields: session_id; age_seconds (since the reading); state and source (the verdict's state and
    tier); matched_rule (the verdict's reason); disagreement_reason (the same reason, only while the
    state is unknown, so a client can show "why unknown" without testing the state); stale; revision.
    """

    session_id: str
    age_seconds: float
    state: str
    source: str
    matched_rule: str
    disagreement_reason: Optional[str] = None
    stale: bool
    revision: int


class AttentionDiagnostics(BaseModel):
    """The route's whole answer. Fields: available (a watcher is running), observations."""

    available: bool
    observations: List[ObservationDiagnostic]


def describe(session_id: str, observation: Any, instant: datetime, unknown_state: str) -> ObservationDiagnostic:
    verdict = observation.verdict
    return ObservationDiagnostic(
        session_id=session_id,
        age_seconds=max(0, (instant - observation.observed_at).total_seconds()),
        state=verdict.state, source=verdict.tier, matched_rule=verdict.reason,
        disagreement_reason=verdict.reason if verdict.state == unknown_state else None,
        stale=observation.stale, revision=observation.revision,
    )
