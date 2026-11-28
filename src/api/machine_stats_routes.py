
from __future__ import annotations

import asyncio
from typing import Any, List, Mapping, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from src.api.auth import require_auth
from src.core.machine_stats import MachineSampler, MachineStatsWatch
from src.core.machine_stats.sample import CACHE_SECONDS
from src.core.pack.machines import exchange

router = APIRouter(tags=["machine-stats"])


class MachineVitalsEntry(BaseModel):
    """One computer's live machine vitals inside the Pack."""

    install_id: str
    label: str
    is_self: bool = False
    cpu_percent: Optional[float] = None
    cpu_count: Optional[int] = None
    memory_percent: Optional[float] = None
    memory_used_bytes: Optional[int] = None
    memory_total_bytes: Optional[int] = None
    disk_percent: Optional[float] = None
    disk_free_bytes: Optional[int] = None
    disk_total_bytes: Optional[int] = None
    load_1: Optional[float] = None
    load_5: Optional[float] = None
    load_15: Optional[float] = None
    uptime_seconds: Optional[int] = None
    live_agents: Optional[int] = None


class MachineVitalsAggregate(BaseModel):
    """Deterministic Pack-wide aggregate vitals across all reporting Pack computers."""

    machine_count: int
    cpu_percent: Optional[float] = None
    cpu_count: Optional[int] = None
    memory_percent: Optional[float] = None
    memory_used_bytes: Optional[int] = None
    memory_total_bytes: Optional[int] = None
    disk_percent: Optional[float] = None
    disk_free_bytes: Optional[int] = None
    disk_total_bytes: Optional[int] = None
    load_1: Optional[float] = None
    load_5: Optional[float] = None
    load_15: Optional[float] = None
    uptime_seconds: Optional[int] = None
    live_agents: Optional[int] = None


class MachineStats(BaseModel):
    """One reading. Every figure is None when it could not be measured (never a false zero)."""

    cpu_percent: Optional[float] = None
    cpu_count: Optional[int] = None
    memory_percent: Optional[float] = None
    memory_used_bytes: Optional[int] = None
    memory_total_bytes: Optional[int] = None
    disk_percent: Optional[float] = None
    disk_free_bytes: Optional[int] = None
    disk_total_bytes: Optional[int] = None
    load_1: Optional[float] = None
    load_5: Optional[float] = None
    load_15: Optional[float] = None
    uptime_seconds: Optional[int] = None
    machines: List[MachineVitalsEntry] = Field(default_factory=list)
    pack_aggregate: Optional[MachineVitalsAggregate] = None


def _state_dir() -> str:
    from src.config import settings

    return str(settings.get_state_dir())


def watch_for(app_state: Any) -> MachineStatsWatch:
    watch = getattr(app_state, "machine_stats_watch", None)
    if watch is None:
        watch = MachineStatsWatch(MachineSampler(_state_dir))
        app_state.machine_stats_watch = watch
    return watch


def _mean_opt(values: List[Optional[float]], digits: int = 1) -> Optional[float]:
    present = [float(v) for v in values if v is not None]
    return round(sum(present) / len(present), digits) if present else None


def _sum_int_opt(values: List[Optional[int]]) -> Optional[int]:
    present = [int(v) for v in values if v is not None]
    return sum(present) if present else None


def _sum_float_opt(values: List[Optional[float]], digits: int = 2) -> Optional[float]:
    present = [float(v) for v in values if v is not None]
    return round(sum(present), digits) if present else None


def _compute_aggregate(entries: List[MachineVitalsEntry]) -> MachineVitalsAggregate:
    mem_used = _sum_int_opt([e.memory_used_bytes for e in entries])
    mem_total = _sum_int_opt([e.memory_total_bytes for e in entries])
    if mem_used is not None and mem_total is not None and mem_total > 0:
        mem_pct: Optional[float] = round(100.0 * mem_used / mem_total, 1)
    else:
        mem_pct = _mean_opt([e.memory_percent for e in entries], digits=1)

    disk_free = _sum_int_opt([e.disk_free_bytes for e in entries])
    disk_total = _sum_int_opt([e.disk_total_bytes for e in entries])
    if disk_free is not None and disk_total is not None and disk_total > 0:
        disk_pct: Optional[float] = round(100.0 * (disk_total - disk_free) / disk_total, 1)
    else:
        disk_pct = _mean_opt([e.disk_percent for e in entries], digits=1)

    uptimes = [e.uptime_seconds for e in entries if e.uptime_seconds is not None]
    return MachineVitalsAggregate(
        machine_count=len(entries),
        cpu_percent=_mean_opt([e.cpu_percent for e in entries], digits=1),
        cpu_count=_sum_int_opt([e.cpu_count for e in entries]),
        memory_percent=mem_pct,
        memory_used_bytes=mem_used,
        memory_total_bytes=mem_total,
        disk_percent=disk_pct,
        disk_free_bytes=disk_free,
        disk_total_bytes=disk_total,
        load_1=_sum_float_opt([e.load_1 for e in entries], digits=2),
        load_5=_sum_float_opt([e.load_5 for e in entries], digits=2),
        load_15=_sum_float_opt([e.load_15 for e in entries], digits=2),
        uptime_seconds=max(uptimes) if uptimes else None,
        live_agents=_sum_int_opt([e.live_agents for e in entries]),
    )


def build_pack_machine_stats(
    reading: Mapping[str, Any],
    *,
    self_id: str,
    self_label: str,
    peer_telemetry: Optional[Mapping[str, Mapping[str, Any]]] = None,
    self_live_agents: Optional[int] = None,
) -> MachineStats:
    self_entry = MachineVitalsEntry(
        install_id=self_id,
        label=self_label,
        is_self=True,
        cpu_percent=reading.get("cpu_percent"),
        cpu_count=reading.get("cpu_count"),
        memory_percent=reading.get("memory_percent"),
        memory_used_bytes=reading.get("memory_used_bytes"),
        memory_total_bytes=reading.get("memory_total_bytes"),
        disk_percent=reading.get("disk_percent"),
        disk_free_bytes=reading.get("disk_free_bytes"),
        disk_total_bytes=reading.get("disk_total_bytes"),
        load_1=reading.get("load_1"),
        load_5=reading.get("load_5"),
        load_15=reading.get("load_15"),
        uptime_seconds=reading.get("uptime_seconds"),
        live_agents=self_live_agents,
    )
    entries: List[MachineVitalsEntry] = [self_entry]
    for origin_iid, tel in (peer_telemetry or {}).items():
        if origin_iid == self_id or not isinstance(tel, Mapping):
            continue
        machine = tel.get("machine")
        if not isinstance(machine, Mapping) or not machine:
            continue
        entries.append(
            MachineVitalsEntry(
                install_id=str(origin_iid),
                label=str(tel.get("label") or origin_iid),
                is_self=False,
                cpu_percent=machine.get("cpu_percent"),
                cpu_count=machine.get("cpu_count"),
                memory_percent=machine.get("memory_percent"),
                memory_used_bytes=machine.get("memory_used_bytes"),
                memory_total_bytes=machine.get("memory_total_bytes"),
                disk_percent=machine.get("disk_percent"),
                disk_free_bytes=machine.get("disk_free_bytes"),
                disk_total_bytes=machine.get("disk_total_bytes"),
                load_1=machine.get("load_1"),
                load_5=machine.get("load_5"),
                load_15=machine.get("load_15"),
                uptime_seconds=machine.get("uptime_seconds"),
                live_agents=machine.get("live_agents"),
            )
        )
    entries.sort(key=lambda e: (e.label.lower(), e.install_id))
    aggregate = _compute_aggregate(entries) if len(entries) > 1 else None
    return MachineStats(**reading, machines=entries, pack_aggregate=aggregate)


def _read_machine_stats_sync(watch: MachineStatsWatch) -> MachineStats:
    from src.core.pack.globalsync import mesh_telemetry

    reading = watch.sampler.read(CACHE_SECONDS)
    runtime = exchange.RUNTIME
    self_id = runtime.install_id if runtime is not None and runtime.install_id else "local"
    self_label = runtime.label if runtime is not None and runtime.label else "this computer"
    peers = mesh_telemetry.active_peers()
    return build_pack_machine_stats(reading, self_id=self_id, self_label=self_label, peer_telemetry=peers)


@router.get("/machine-stats", response_model=MachineStats, dependencies=[Depends(require_auth)])
async def get_machine_stats(request: Request) -> MachineStats:
    """The host's vitals now (plus Pack-wide deterministic ``machines`` and ``pack_aggregate`` when peers report), taking a sampler lease."""
    watch = watch_for(request.app.state)
    watch.touch()
    return await asyncio.to_thread(_read_machine_stats_sync, watch)
