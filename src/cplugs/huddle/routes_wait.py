
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Request, Response
from pydantic import BaseModel, ConfigDict, Field

from src.cplugs.huddle import wait_resolve
from src.cplugs.huddle.routes import Ctx, mapped_errors, router
from src.cplugs.sdk import CplugContext, add_public_post, has_valid_bearer, rate_limited

RATE_LIMIT = "20/minute"


class ResolveRequest(BaseModel):
    """The callback body. ``token`` is optional only because the owner's bearer is the other way in."""

    model_config = ConfigDict(extra="forbid")
    token: Optional[str] = Field(default=None, max_length=200)
    result: str
    reason: Optional[str] = Field(default=None, max_length=wait_resolve.MAX_REASON)


@rate_limited(RATE_LIMIT)
async def resolve_wait(item_id: int, body: ResolveRequest, request: Request, response: Response, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    authed = await has_valid_bearer(request)
    with mapped_errors():
        return await wait_resolve.resolve(ctx, item_id, body.result, body.reason, token=body.token, authed=authed)


add_public_post(router, "huddle", "/items/{item_id}/wait/resolve", resolve_wait)
