
from __future__ import annotations

from typing import Dict, Optional, Union

from fastapi import APIRouter, Depends, HTTPException

from src.api.auth import require_auth
from src.core.notifications import engine

router = APIRouter(prefix="/notifications", tags=["notifications"], dependencies=[Depends(require_auth)])


@router.post("/destinations/{dest_id}/test")
async def post_test(dest_id: str) -> Dict[str, Optional[Union[bool, str, int]]]:
    """Send the test message. Output: {ok, failure, status_code}; raises 503, 404 or 429 as described above."""
    active = engine.current_engine()
    if active is None:
        raise HTTPException(status_code=503, detail="notifications are not running")
    outcome = await active.send_test(dest_id)
    if not outcome.found:
        raise HTTPException(status_code=404, detail="unknown destination")
    if outcome.limited:
        raise HTTPException(status_code=429, detail="test sent too recently")
    result = outcome.result
    return {"ok": result.ok, "failure": result.failure.value if result.failure else None,
            "status_code": result.status_code}
