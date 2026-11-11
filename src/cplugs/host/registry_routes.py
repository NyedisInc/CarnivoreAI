
from __future__ import annotations

from typing import Any, Dict, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from src.api.auth import require_auth
from src.cplugs.host import registry_boot
from src.cplugs.host.peer_refusal import refuse_peer_token_writes

router = APIRouter(prefix="/cplug-owner", tags=["cplugs"], dependencies=[Depends(refuse_peer_token_writes), Depends(require_auth)])


class ResolveBody(BaseModel):
    """The owner's choice for a registry file older than its database."""

    model_config = ConfigDict(extra="forbid")
    choice: Literal["keep", "backup"]


@router.put("/registry/resolve")
async def put_resolve(body: ResolveBody, request: Request) -> Dict[str, Any]:
    """Keep the older file or use the backup, then allow plugin writes again. Output: ``{ok: true}``; 409 ``no_readable_copy`` when ``backup`` found nothing."""
    import asyncio  # noqa: PLC0415

    from src.cplugs.host import runtime  # noqa: PLC0415

    state_dir = runtime.host_for(request.app).state_dir
    if not await asyncio.to_thread(registry_boot.resolve, state_dir, body.choice):
        raise HTTPException(status_code=409, detail={"code": "no_readable_copy", "detail": "no readable copy was found; plugin settings stay read only"})
    return {"ok": True}
