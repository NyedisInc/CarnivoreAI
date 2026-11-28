
from __future__ import annotations

import dataclasses
import threading
from typing import Any, Callable, Dict, List, Optional

import structlog

from src.core.pack.jobs import folders
from src.core.pack.jobs.types import CAP_NEEDS, AdmitBody, HostState, JobError
from src.core.pack.machines import capabilities
from src.core.pack.placement import needs as needs_mod
from src.core.pack.placement.workload import Workload
from src.core.pack.reserve.holds import HOLDS

log = structlog.get_logger(__name__)
capabilities.register(CAP_NEEDS)

_MEMBER_LOCK = threading.Lock()

ADMIT_HOLD_S = 120.0
START_HOLD_S = 900.0
RUN_HOLD_S = 90.0


def own_snapshot() -> Optional[Dict[str, Any]]:
    from src.core.pack.machines import runtime

    wired = runtime.wiring()
    return wired.runtime.own_snapshot() if wired is not None else None


LOOK_KEYS = ("v", "install_id", "label", "app_version", "taken_at", "can", "pressure", "specs", "load", "toolchain", "battery", "capabilities", "throttled")
LOOK_RESERVE_KEYS = ("level", "cpu_pct", "mem_pct")


def look_snapshot(snap: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(snap, dict):
        return None
    out: Dict[str, Any] = {k: snap[k] for k in LOOK_KEYS if k in snap}
    reserve = snap.get("reserve")
    if isinstance(reserve, dict):
        out["reserve"] = {k: reserve[k] for k in LOOK_RESERVE_KEYS if k in reserve}
    return out


def enforce_member_hosting(project_uid: str, company_uid: Optional[str]) -> None:
    from src.core.pack.machines import config_state
    from src.core.pack.machines.restrictions import ACTION_HOST_AGENTS, enforce

    enforce(config_state.default().restrictions(), ACTION_HOST_AGENTS, project_uid=project_uid, company_uid=company_uid, live_agents=0)


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


def member_load(host: Any, caller: str, now: Optional[float] = None, exclude: Optional[str] = None) -> int:
    now = host._clock() if now is None else now  # noqa: SLF001
    ids = set(HOLDS.keys_of(caller))
    store = host.store
    live = (HostState.PREPARING, HostState.RUNNING, HostState.PARKED)
    ids.update(r.job_id for r in store.host_list(list(live)) if r.caller_install == caller)
    ids.update(r.job_id for r in store.host_list([HostState.STOPPED]) if r.caller_install == caller and (r.keep_until or 0) > now)
    exited = {r.job_id for r in store.host_list([HostState.EXITED]) if r.caller_install == caller}
    if exited:
        bound = {s["job_id"] for s in store.slot_rows() if s["job_id"]}
        ids.update(exited & bound)
    ids.discard(exclude)
    return len(ids)


def _hold(host: Any, key: str, owner: str, project_uid: str, work: Workload, ttl_s: float, member: bool = False) -> None:
    said: List[str] = []

    def fits(held_cpu: float, held_ram: float) -> bool:
        bigger = dataclasses.replace(work, est_cpu_cores=work.est_cpu_cores + held_cpu, est_ram_gb=work.est_ram_gb + held_ram)
        sentence = host._admit(bigger)
        if sentence:
            said.append(sentence)
        return not sentence

    if folders.busy_count(host.store, project_uid) >= host_max_slots():
        raise JobError("no_free_slot", f"all {host_max_slots()} folders for this project are busy", 409)
    if member:
        from src.core.pack.jobs import member_view

        with _MEMBER_LOCK:
            if member_load(host, owner, exclude=key) >= member_view.MAX_JOBS_PER_MEMBER:
                raise JobError("host_busy", f"this computer already holds {member_view.MAX_JOBS_PER_MEMBER} jobs for that computer", 503)
            _take(key, owner, work, ttl_s, fits, said)
        return
    _take(key, owner, work, ttl_s, fits, said)


def _take(key: str, owner: str, work: Workload, ttl_s: float, fits: Callable[[float, float], bool], said: List[str]) -> None:
    if not HOLDS.try_hold(key, owner, work.est_cpu_cores, work.est_ram_gb, ttl_s, fits):
        raise JobError("host_busy", said[-1] if said else "this computer holds room for as many jobs as it can", 503)


def host_max_slots() -> int:
    from src.core.pack.jobs import host

    return host.MAX_SLOTS


def admit(host: Any, caller: str, body: AdmitBody, work: Workload, member: bool = False) -> None:
    snapshot = own_snapshot()
    if body.needs:
        check_needs(body.needs, snapshot)
    check_pegged(snapshot)
    _hold(host, body.job_id, caller, body.project_uid, work, ADMIT_HOLD_S, member)


def start_hold(host: Any, caller: str, job_id: str, project_uid: str, work: Workload, member: bool = False) -> None:
    _hold(host, job_id, caller, project_uid, work, START_HOLD_S, member)


def runner_started(job_id: str) -> None:
    HOLDS.extend(job_id, RUN_HOLD_S)
    _notify_load_shift()


def update_measured(job_id: str, cpu_cores: float, ram_gb: float) -> bool:
    return HOLDS.set_measured(job_id, cpu_cores, ram_gb)


def drop(job_id: str) -> None:
    HOLDS.drop(job_id)
    _notify_load_shift()


def _notify_load_shift() -> None:
    try:
        from src.core.pack.machines import runtime

        wired = runtime.wiring()
        if wired is not None:
            wired.runtime.notify_load_shift()
    except Exception:  # noqa: BLE001
        pass
