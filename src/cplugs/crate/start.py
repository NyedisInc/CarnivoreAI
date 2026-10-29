
from __future__ import annotations

import asyncio
from typing import Any

import structlog

from src.cplugs.crate import constants as K
from src.cplugs.crate import extracts, service
from src.cplugs.crate.jobs import runner, state
from src.cplugs.crate.jobs.sweep import sweep_interrupted

logger = structlog.get_logger()


def tidy(ctx: Any) -> dict:
    env = service.env_of(ctx)
    swept = sweep_interrupted(env)
    pruned = state.prune(state.jobs_dir(env.work))
    folders = extracts.prune_extracts(env.work)
    return {"swept": swept, "pruned_jobs": pruned, "pruned_extracts": folders}


async def on_start(ctx: Any) -> None:
    counts = await asyncio.to_thread(tidy, ctx)
    logger.info("crate_started", **counts)


async def on_stop(ctx: Any) -> None:
    job_id = runner.cancel_all()
    if job_id is None:
        return
    ended = await asyncio.to_thread(runner.join, K.STOP_JOIN_S)
    if not ended:
        logger.warning("crate_job_still_stopping", job_id=job_id)
