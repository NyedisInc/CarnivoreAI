
from __future__ import annotations

from typing import Any

from src.core.attention.registry_record import REG_IDLE, REG_SHELL
from src.core.background_work.measured import STATE_NONE, STATE_RUNNING


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


def only_servers_run(evidence: Any) -> bool:
    measure = getattr(evidence, "background_process", None)
    registry = getattr(evidence, "registry", None)
    return (
        measure is not None
        and measure.state == STATE_RUNNING
        and (measure.count or 0) > 0
        and measure.servers >= measure.count
        and registry is not None
        and registry.known
        and registry.status in (REG_IDLE, REG_SHELL)
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


def leftover_claims(evidence: Any) -> int:
    leftovers = getattr(evidence, "background_leftovers", None)
    facts = getattr(evidence, "transcript", None)
    ids = tuple(getattr(facts, "open_background_task_ids", ()) or ())
    count = int(getattr(facts, "open_background_tasks", 0) or 0)
    if not leftovers or count <= 0 or len(ids) != count:
        return 0
    return sum(1 for task_id in ids if task_id in leftovers)


def standing_background_claims(evidence: Any) -> int:
    if measurement_overrules_claims(evidence) or only_servers_run(evidence):
        return 0
    return max(claims_after_epoch(evidence) - leftover_claims(evidence), 0)


__all__ = [
    "claims_after_epoch", "leftover_claims", "measurement_overrules_claims", "only_servers_run",
    "standing_background_claims",
]
