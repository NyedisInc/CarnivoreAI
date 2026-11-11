
from __future__ import annotations

from fastapi import Depends, HTTPException

from src.cplugs.reviewboard.public.availability import AVAILABILITY
from src.cplugs.reviewboard.public.settings import links_enabled
from src.cplugs.sdk import CplugContext, cplug_context


def require_public_links(ctx: CplugContext = Depends(cplug_context("reviewboard"))) -> None:
    if not links_enabled(ctx.settings_now()):
        raise HTTPException(status_code=404, detail={"code": "public_links_off", "detail": "public links are off"})


def require_available(ctx: CplugContext = Depends(cplug_context("reviewboard"))) -> None:
    if not AVAILABILITY.ok:
        raise HTTPException(status_code=503, detail={"code": "public_links_unavailable", "detail": f"public links are unavailable: {AVAILABILITY.reason}"})
