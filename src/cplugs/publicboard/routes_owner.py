
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from src.cplugs.publicboard import links, minting
from src.cplugs.publicboard.health import HEALTH
from src.cplugs.publicboard.service import SERVICE
from src.cplugs.sdk import CplugContext, cplug_context, cplug_router

router = cplug_router("publicboard")
Ctx = Depends(cplug_context("publicboard"))


class MintBody(BaseModel):
    """The mint body. A ``ttl`` outside the three allowed values fails validation (422), it is never rounded."""

    model_config = ConfigDict(extra="forbid")
    board: str = Field(min_length=1, max_length=200)
    ttl: links.Ttl
    mode: links.Mode = "pinned"
    revision: Optional[str] = Field(default=None, pattern=r"^r[1-9][0-9]*$", max_length=16)


@router.get("/status")
async def status() -> Dict[str, Any]:
    """The plugin's status for the owner. Output: {listening, forwarding_ok, message, missing_count, last_missing_at}.

    ``message`` says "the proxy is not forwarding the visitor address" while requests keep arriving with no usable ``X-Forwarded-For``.
    """
    return {"listening": SERVICE.listener is not None, **HEALTH.snapshot()}


@router.post("/links", status_code=201)
async def mint_link(body: MintBody, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Mint a link. Output: {token, link}; the token appears only in this answer."""
    try:
        made = await minting.mint_link(ctx, body.board, body.ttl, body.mode, body.revision)
    except minting.MintRefused as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "detail": str(exc), **exc.extra}) from exc
    return {"token": made["token"], "link": made["link"].as_wire()}


@router.get("/links")
async def list_links(board: Optional[str] = Query(None, min_length=1, max_length=200), ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """The links, newest first. Output: {links}."""
    rows = await asyncio.to_thread(links.list_links, ctx.storage, board)
    return {"links": [row.as_wire() for row in rows]}


@router.delete("/links/{link_id}")
async def revoke_one(link_id: str, ctx: CplugContext = Ctx) -> Dict[str, int]:
    """Revoke one link. Output: {revoked: 1}. Raises 404 publicboard_no_link."""
    if not await asyncio.to_thread(links.revoke_link, ctx.storage, link_id):
        raise HTTPException(status_code=404, detail={"code": "publicboard_no_link", "detail": "no live link with that id"})
    return {"revoked": 1}


@router.delete("/links")
async def revoke_many(board: Optional[str] = Query(None, min_length=1, max_length=200), all_links: bool = Query(False, alias="all"), ctx: CplugContext = Ctx) -> Dict[str, int]:
    """Revoke every live link of one board, or all. Output: {revoked: n}. Raises 422 unless exactly one of ``board`` and ``all`` is given."""
    if (board is None) == (not all_links):
        raise HTTPException(status_code=422, detail={"code": "publicboard_invalid", "detail": "give exactly one of board or all=true"})
    count = await asyncio.to_thread(links.revoke_all, ctx.storage) if all_links else await asyncio.to_thread(links.revoke_board, ctx.storage, board or "")
    return {"revoked": count}
