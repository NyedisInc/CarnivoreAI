from __future__ import annotations

import asyncio
import sqlite3

import structlog
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict

from src.api.stats_routes import _store, _run, router
from src.core.pipeline.plugin_db import PluginUnavailable
from src.core.session_change_notice import publish
from src.core.stats import config, reset

logger = structlog.get_logger()


class ClearRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool


def _job(request: Request) -> reset.ClearJob:
    state = request.app.state
    if getattr(state, "stats_clear_job", None) is None:
        state.stats_clear_job = reset.ClearJob()
    return state.stats_clear_job


def _backfill(store, scheduler) -> dict:
    from src.core.stats.plugin.progress import progress

    running = bool((scheduler.status() if scheduler is not None else {}).get("backfill_running"))
    found = progress(store.state_dir)
    state = "running" if running or found["pending_sources"] > 0 else "idle"
    return {"state": state, **found}


@router.get("/maintenance", response_model=None)
async def get_maintenance(request: Request):
    store = _store(request)
    settings = await _run(config.get_settings, store)
    scheduler = getattr(request.app.state, "stats_scheduler", None)
    return {"enabled": settings["enabled"], "revision": settings["revision"],
            "db_bytes": await asyncio.to_thread(reset.file_bytes, store),
            "clear": _job(request).public(),
            "backfill": await asyncio.to_thread(_backfill, store, scheduler)}


async def _clear(request: Request, store, job: reset.ClearJob) -> None:
    try:
        await asyncio.to_thread(reset.clear_stats, store, job)
    except (OSError, sqlite3.Error, reset.StatsStillOn, reset.NotEnoughSpace, PluginUnavailable) as exc:
        job.state, job.error = "failed", type(exc).__name__
        return
    scheduler = getattr(request.app.state, "stats_scheduler", None)
    if scheduler is not None:
        scheduler.after_clear()
    revision = await asyncio.to_thread(store.revision)
    publish(request.app.state, {"type": "stats.changed", "revision": revision, "source_health": "ok"})


@router.post("/clear", response_model=None, status_code=202)
async def post_clear(request: Request, value: ClearRequest):
    """Start clearing collected stats and reclaiming the disk; poll `/stats/maintenance`."""
    if not value.confirm:
        raise HTTPException(422, detail={"code": "confirm_required"})
    store = _store(request)
    job = _job(request)
    if job.state == "running":
        raise HTTPException(409, detail={"code": "clear_running"})
    if (await _run(config.get_settings, store))["enabled"]:
        raise HTTPException(409, detail={"code": "stats_must_be_off"})
    free = await asyncio.to_thread(reset.free_space, store)
    if free < reset.MIN_FREE_BYTES:
        raise HTTPException(507, detail={"code": "not_enough_disk", "free_bytes": free,
                                         "needed_bytes": reset.MIN_FREE_BYTES})
    job.state, job.phase, job.error = "running", "preparing", ""
    request.app.state.stats_clear_task = asyncio.create_task(_clear(request, store, job), name="stats-clear")
    return job.public()
