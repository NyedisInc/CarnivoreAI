
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from src.api.auth import require_auth
from src.core.argent import detector
from src.core.argent.lifecycle import PORT_NAME
from src.core.argent.runtime import get_runtime
from src.cplugs.sdk import ports

router = APIRouter(prefix="", tags=["argent"], dependencies=[Depends(require_auth)])


def _detect_sync() -> Dict[str, Any]:
    login = get_runtime().store.get_login()
    return detector.detect(str(login["tenant_id"]) if login else "", feature_on=ports.get(PORT_NAME) is not None)


@router.get("/precedence")
async def get_precedence() -> Dict[str, Any]:
    """Rows whose settings override the tether, rows tethered while the switch is off, and whether the shared settings file carries a gateway env."""
    return await run_in_threadpool(_detect_sync)
