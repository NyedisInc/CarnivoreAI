
from __future__ import annotations

import dataclasses
from typing import Any, Callable, Dict, List, Optional

import structlog

from src.core.pack.jobs import folders
from src.core.pack.jobs.types import CAP_NEEDS, AdmitBody, JobError
from src.core.pack.machines import capabilities
from src.core.pack.placement import needs as needs_mod
from src.core.pack.placement.workload import Workload
from src.core.pack.reserve.holds import HOLDS

log = structlog.get_logger(__name__)
capabilities.register(CAP_NEEDS)

ADMIT_HOLD_S = 120.0
START_HOLD_S = 900.0
RUN_HOLD_S = 90.0


def own_snapshot() -> Optional[Dict[str, Any]]:
    from src.core.pack.machines import runtime

    wired = runtime.wiring()
    return wired.runtime.own_snapshot() if wired is not None else None


def check_needs(words: List[str], snapshot: Optional[Dict[str, Any]]) -> None:
    try:
        wanted = needs_mod.parse_all(words, limit=24)
    except ValueError as exc:
        raise JobError("bad_request", str(exc), 422) from exc
    lacking = [r for r in (needs_mod.unmet_reason(snapshot, n) for n in wanted) if r]
    if lacking:
        raise JobError("lacks_tool", f"this computer {'; '.join(lacking)}", 409)


def check_pegged(snapshot: Optional[Dict[str, Any]]) -> None:
    gauge = (snapshot or {}).get("pressure")
    if isinstance(gauge, dict) and gauge.get("pegged") is True:
        raise JobError("pegged", f"this computer is pegged: {str(gauge.get('why') or 'past its own reserve line')[:120]}", 503)


def _hold(host: Any, key: str, owner: str, project_uid: str, work: Workload, ttl_s: float) -> None:
    said: List[str] = []

    def fits(held_cpu: float, held_ram: float) -> bool:
        bigger = dataclasses.replace(work, est_cpu_cores=work.est_cpu_cores + held_cpu, est_ram_gb=work.est_ram_gb + held_ram)
        sentence = host._admit(bigger)
        if sentence:
            said.append(sentence)
        return not sentence

    if folders.busy_count(host.store, project_uid) >= host_max_slots():
        raise JobError("no_free_slot", f"all {host_max_slots()} folders for this project are busy", 409)
    if not HOLDS.try_hold(key, owner, work.est_cpu_cores, work.est_ram_gb, ttl_s, fits):
        raise JobError("host_busy", said[-1] if said else "this computer holds room for as many jobs as it can", 503)


def host_max_slots() -> int:
    from src.core.pack.jobs import host

    return host.MAX_SLOTS


def admit(host: Any, caller: str, body: AdmitBody, work: Workload) -> None:
    snapshot = own_snapshot()
    if body.needs:
        check_needs(body.needs, snapshot)
    check_pegged(snapshot)
    _hold(host, body.job_id, caller, body.project_uid, work, ADMIT_HOLD_S)


def start_hold(host: Any, caller: str, job_id: str, project_uid: str, work: Workload) -> None:
    _hold(host, job_id, caller, project_uid, work, START_HOLD_S)


def runner_started(job_id: str) -> None:
    HOLDS.extend(job_id, RUN_HOLD_S)


def drop(job_id: str) -> None:
    HOLDS.drop(job_id)
