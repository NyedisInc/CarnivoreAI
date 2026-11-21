
from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import APIRouter, Depends, Query
from fastapi.concurrency import run_in_threadpool

from src.api.auth import require_auth
from src.api.error_response import refusal_error
from src.core.pack.jobs import boot, metrics
from src.core.pack.jobs.types import JobError

router = APIRouter(tags=["pack-jobs"], dependencies=[Depends(require_auth)])


def _report(days: int) -> Dict[str, Any]:
    try:
        store = boot.engine().store
    except JobError as exc:
        raise refusal_error(exc) from exc
    return metrics.report(store, days, now=time.time())


@router.get("/pack/jobs/metrics")
async def get_metrics(days: int = Query(7, ge=1, le=metrics.KEEP_DAYS)) -> Dict[str, Any]:
    """P3, R3 and the last 24 load hours of this computer. Raises 422 for ``days`` outside 1..30, 503 jobs_not_ready."""
    return await run_in_threadpool(_report, days)
