
from __future__ import annotations

from typing import Dict, Optional, Union

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from src.api.auth import require_auth
from src.core.notifications import engine, types

router = APIRouter(prefix="/notifications", tags=["notifications"], dependencies=[Depends(require_auth)])


class TestBody(BaseModel):
    """``POST .../test``: an optional ``type_id`` makes the test that type's sample card (422 for an unregistered type)."""

    model_config = ConfigDict(extra="forbid")

    type_id: Optional[str] = None


@router.post("/destinations/{dest_id}/test")
async def post_test(dest_id: str, body: Optional[TestBody] = None) -> Dict[str, Optional[Union[bool, str, int]]]:
    """Send the test message (a type's sample card when ``type_id`` is given).

    Output: {ok, failure, status_code}; raises 503, 404, 422 (bad type) or 429 as described above.
    """
    type_id = body.type_id if body else None
    if type_id is not None:
        type_id = types.canonical(type_id)
        if not types.is_registered(type_id):
            raise HTTPException(status_code=422, detail="not a notification type")
    active = engine.current_engine()
    if active is None:
        raise HTTPException(status_code=503, detail="notifications are not running")
    outcome = await active.send_test(dest_id, type_id)
    if not outcome.found:
        raise HTTPException(status_code=404, detail="unknown destination")
    if outcome.limited:
        raise HTTPException(status_code=429, detail="test sent too recently")
    result = outcome.result
    return {"ok": result.ok, "failure": result.failure.value if result.failure else None,
            "status_code": result.status_code}
