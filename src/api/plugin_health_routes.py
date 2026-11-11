
from __future__ import annotations

import asyncio
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request

from src.api.auth import require_auth
from src.core.plugin_health.gather import build_report
from src.cplugs.host import runtime

router = APIRouter(prefix="/cplug-owner", tags=["cplugs"], dependencies=[Depends(require_auth)])


@router.get("/health")
async def get_health(request: Request) -> Dict[str, Any]:
    """The plugin health report. Output: {counts, rows, orphan_data, removed, stale_state, problems, registry_generation, registry_source}."""
    host = runtime.host_for(request.app)
    live = getattr(request.app.state, "sidecar_runtime", None)
    report = await asyncio.to_thread(build_report, host, live)
    return report.as_wire()
