
from __future__ import annotations

import asyncio
from typing import Any, Dict

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.api.auth import require_auth
from src.core.retention.service import get_service

router = APIRouter(prefix="/maintenance/retention", tags=["retention"], dependencies=[Depends(require_auth)])


class RetentionRunRequest(BaseModel):
    """Body of the run-now route. ``dry_run`` defaults to true so a bare POST never moves anything."""

    dry_run: bool = True


@router.get("")
async def get_retention_status() -> Dict[str, Any]:
    """Config, running flag and the last real run's report (null before the first), with no I/O.

    Output: {enabled, config, running, last_run}.
    Example: GET /maintenance/retention -> {"enabled": true, "last_run": null, ...}
    """
    return get_service().status()


@router.post("/run")
async def run_retention_now(body: RetentionRunRequest | None = None) -> Dict[str, Any]:
    """Run retention now, off the event loop. Dry run (default) lists what it would do; otherwise does it.

    Input: body {dry_run: bool}. Output: the run's report {started_at, dry_run, drive_ready, drive_detail, counts, errors,
    actions[]}. With the drive missing a real run moves nothing and every action reads skipped.
    Example: POST /maintenance/retention/run {"dry_run": false} -> {"counts": {"done": 3}, ...}
    """
    dry = True if body is None else body.dry_run
    report = await asyncio.to_thread(get_service().run, dry)
    return report.to_dict()
