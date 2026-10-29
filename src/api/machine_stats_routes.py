
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from src.api.auth import require_auth
from src.core.machine_stats import MachineSampler, MachineStatsWatch
from src.core.machine_stats.sample import CACHE_SECONDS

router = APIRouter(tags=["machine-stats"])


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


def _state_dir() -> str:
    """The state directory, whose volume's free space the disk figure reports."""
    from src.config import settings

    return str(settings.get_state_dir())


def watch_for(app_state) -> MachineStatsWatch:
    watch = getattr(app_state, "machine_stats_watch", None)
    if watch is None:
        watch = MachineStatsWatch(MachineSampler(_state_dir))
        app_state.machine_stats_watch = watch
    return watch


@router.get("/machine-stats", response_model=MachineStats, dependencies=[Depends(require_auth)])
async def get_machine_stats(request: Request) -> MachineStats:
    """The host's vitals now, and a lease that keeps the sampler pushing while this client looks."""
    watch = watch_for(request.app.state)
    watch.touch()
    reading = await asyncio.to_thread(watch.sampler.read, CACHE_SECONDS)
    return MachineStats(**reading)
