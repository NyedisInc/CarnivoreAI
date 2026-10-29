
from __future__ import annotations

import asyncio
from typing import Any, Dict

from fastapi import APIRouter, Depends

from src.api.auth import require_auth
from src.core.self_check import monitor

router = APIRouter(prefix="/self-check", tags=["self-check"], dependencies=[Depends(require_auth)])


@router.get("")
async def get_self_check() -> Dict[str, Any]:
    """Run the checks now and answer the report. Output: {status, checks}."""
    return await asyncio.to_thread(monitor.report)
