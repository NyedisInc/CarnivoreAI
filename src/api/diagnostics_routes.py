
from __future__ import annotations

import asyncio
from typing import Any, Dict

from fastapi import APIRouter, Depends

from src.api.auth import require_auth
from src.core.diagnostics import build_bundle

router = APIRouter(tags=["diagnostics"], dependencies=[Depends(require_auth)])


@router.get("/diagnostics")
async def get_diagnostics() -> Dict[str, Any]:
    """Version, uptime, pid, port, bind, tmux socket and session count, recent errors, log location, disk free, python, config key names.

    Output: the bundle dict (see ``builder.build_bundle``); a section that could not be measured is null and named in ``notes``.
    Example: GET /api/v1/diagnostics -> {"version": "1.16.1", "process": {"pid": 123, ...}, "notes": []}
    """
    return await asyncio.to_thread(build_bundle, mode="server")
