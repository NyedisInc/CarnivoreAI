
from __future__ import annotations

import asyncio
from typing import Dict

from fastapi import Depends

from src.cplugs.sdk import CplugContext, cplug_context, cplug_router
from src.cplugs.timemachine import service

router = cplug_router("timemachine")
Ctx = Depends(cplug_context("timemachine"))


@router.post("/check")
async def post_check(ctx: CplugContext = Ctx) -> Dict[str, str]:
    """Run one pass now. Input: ctx (fresh per request, so its grants are current). Output: {state, outcome, reason?}."""
    return await asyncio.to_thread(service.run_pass, ctx)
