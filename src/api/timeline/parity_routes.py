
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

from src.api.auth import require_auth
from src.core.timeline.parity import PARITY

router = APIRouter(prefix="/timeline", tags=["timeline"], dependencies=[Depends(require_auth)])


@router.get("/parity")
async def timeline_parity() -> Dict[str, Any]:
    """The shadow comparison's counters, newest day first. Output: dict (``Parity.snapshot``).

    ``async`` on purpose: the counters are written on the event loop by the watcher, so reading them on the same loop
    cannot race a half-made update (REVIEW-T3 item 8). The snapshot is small and reads the store file at most once.
    """
    return PARITY.snapshot()
