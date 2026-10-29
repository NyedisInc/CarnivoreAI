
from __future__ import annotations

from typing import Any

from src.core.attention.registry_record import REG_IDLE
from src.core.background_work.measured import STATE_NONE


def measurement_overrules_claims(evidence: Any) -> bool:
    measure = getattr(evidence, "background_process", None)
    registry = getattr(evidence, "registry", None)
    return (
        measure is not None
        and measure.state == STATE_NONE
        and registry is not None
        and registry.known
        and registry.status == REG_IDLE
    )


def claims_after_epoch(evidence: Any) -> int:
    facts = getattr(evidence, "transcript", None)
    count = int(getattr(facts, "open_background_tasks", 0) or 0)
    registry = getattr(evidence, "registry", None)
    started = registry.started_at if registry is not None and registry.known else None
    times = tuple(getattr(facts, "open_background_launched_at", ()) or ())
    if count <= 0 or started is None or len(times) != count:
        return max(count, 0)
    kept = 0
    for at in times:
        try:
            older = at is not None and at < started
        except TypeError:
            older = False
        kept += 0 if older else 1
    return kept


def standing_background_claims(evidence: Any) -> int:
    if measurement_overrules_claims(evidence):
        return 0
    return claims_after_epoch(evidence)


__all__ = ["claims_after_epoch", "measurement_overrules_claims", "standing_background_claims"]
