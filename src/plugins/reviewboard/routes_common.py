from __future__ import annotations

from fastapi import Depends

from src.plugins.sdk import cplug_context, cplug_router

router = cplug_router("reviewboard")
Ctx = Depends(cplug_context("reviewboard"))
