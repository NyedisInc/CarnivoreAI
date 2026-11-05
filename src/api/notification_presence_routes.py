
from __future__ import annotations

from typing import Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.api.auth import require_auth
from src.core.notifications.presence import presence

router = APIRouter(prefix="/notifications", tags=["notifications"], dependencies=[Depends(require_auth)])


class PresenceBody(BaseModel):
    """Body of the beacon: the tab's client id, whether its screen is active (false drops the lease) and the watched
    session's id ('' for none; feature plan #10)."""

    model_config = ConfigDict(extra="forbid")

    client_id: str
    active: bool
    watched: str = Field(default="", max_length=200, pattern=r"^[A-Za-z0-9_:.-]*$")


@router.post("/presence")
async def post_presence(body: PresenceBody) -> Dict[str, bool]:
    """Hold (or drop) this tab's 60 s screen lease. Raises 422 on a malformed client id."""
    if not presence.beacon(body.client_id, body.active, body.watched):
        raise HTTPException(status_code=422, detail="invalid client_id")
    return {"ok": True}
