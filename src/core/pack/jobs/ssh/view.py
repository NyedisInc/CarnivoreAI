
from __future__ import annotations

import dataclasses
import uuid
from typing import Any, Callable, Dict, List, Optional, Sequence

import structlog

from src.core.hosts.ssh_master import SshTransportError
from src.core.pack.jobs.ssh.readings import FRESH_S, SshReading, shared
from src.core.pack.jobs.target import SSH_PREFIX
from src.core.pack.jobs.types import CAP_JOBS, JobError
from src.core.pack.machines import restrictions as restrictions_mod
from src.core.pack.placement.rule import MachineInput

log = structlog.get_logger(__name__)

HOLD_S = 120.0


def snapshot_of(reading: SshReading) -> Dict[str, Any]:
    rules = restrictions_mod.Restrictions(may_host_agents=reading.takes_work, may_install_tools=False, may_receive_credentials=False)
    snap: Dict[str, Any] = {"toolchain": {}, "battery": None, "reserve": reading.reserve, "restrictions": rules.model_dump()}
    if reading.can is not None:
        snap["can"] = reading.can
    if reading.load is not None:
        snap["load"] = reading.load
    if reading.pressure is not None:
        snap["pressure"] = reading.pressure
    return snap


def machine_of(reading: SshReading, now: float) -> MachineInput:
    fresh = reading.usable and reading.takes_work and reading.taken_at is not None and 0 <= now - reading.taken_at < FRESH_S
    snap = snapshot_of(reading) if (reading.load is not None or not reading.takes_work) else None
    return MachineInput(SSH_PREFIX + reading.host_key, reading.label, snap, fresh, False, False, True, None)


def extend(view: Any, targets: Sequence[SshReading], now: Optional[float] = None,
           hold: Optional[Callable[[str, float, float], None]] = None) -> Any:
    import time

    at = time.time() if now is None else now
    pinned = [r for r in targets if r.pinned]
    if not pinned:
        return view
    caps = {**view.caps, **{SSH_PREFIX + r.host_key: [CAP_JOBS] for r in pinned}}
    return dataclasses.replace(view, peers=[*view.peers, *(machine_of(r, at) for r in pinned)], caps=caps,
                               ssh_hold=hold if hold is not None else view.ssh_hold)


def extend_live(view: Any) -> Any:
    from src.core.pack.jobs import boot

    try:
        store = boot.engine().store
    except JobError:
        return view
    readings = shared(store)
    if not store.ssh_targets_all():
        return view
    try:
        got: List[SshReading] = readings.placement_blocking()
    except (JobError, SshTransportError) as exc:
        log.info("pack_ssh_placement_read_failed", error=type(exc).__name__)
        return view

    def hold(install_id: str, cpu: float, ram_gb: float) -> None:
        key = install_id[len(SSH_PREFIX):]
        readings.hold(key, f"placed-{uuid.uuid4().hex[:12]}", cpu, ram_gb, HOLD_S)

    return extend(view, got, hold=hold)
