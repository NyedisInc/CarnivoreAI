
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException, Path, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from src.plugins.reviewboard.public import announce, drafts, links, minting, presence, responses, visitors
from src.plugins.reviewboard.public import theme as theme_rules
from src.plugins.reviewboard.public.availability import AVAILABILITY
from src.plugins.reviewboard.public.gate import require_available, require_public_links
from src.plugins.reviewboard.public.health import HEALTH
from src.plugins.reviewboard.public.service import SERVICE
from src.plugins.sdk import CplugContext, cplug_context
from src.plugins.reviewboard.public.port import port
from src.plugins.reviewboard.routes_common import router

GATE = [Depends(require_public_links)]
STORE_GATE = [Depends(require_public_links), Depends(require_available)]
Ctx = Depends(cplug_context("reviewboard"))


class MintBody(BaseModel):
    """The mint body. A ``ttl`` outside the three allowed values fails validation (422), it is never rounded."""

    model_config = ConfigDict(extra="forbid")
    board: str = Field(min_length=1, max_length=200)
    ttl: links.Ttl
    mode: links.Mode = "pinned"
    access: links.Access = "answer"
    revision: Optional[str] = Field(default=None, pattern=r"^r[1-9][0-9]*$", max_length=16)
    theme: Optional[Dict[str, str]] = Field(default=None, max_length=theme_rules.MAX_OFFERED)


class ForwardBody(BaseModel):
    """The forward body: the board, and the ids of the responses the owner's window SHOWED (only those still unforwarded go; the visitors' autosaved answers always go)."""

    model_config = ConfigDict(extra="forbid")
    board: str = Field(min_length=1, max_length=200)
    ids: List[int] = Field(max_length=responses.MAX_PER_BOARD)


@router.get("/public/status", dependencies=GATE)
async def status() -> Dict[str, Any]:
    """The status of public links for the owner. Output: {listening, available, unavailable_reason, forwarding_ok, message, missing_count, last_missing_at}.

    ``available`` is false (with a reason word) when the carry of the old store was refused this run (``carry.py``): the board works, public links do not.
    ``message`` says "the proxy is not forwarding the visitor address" while requests keep arriving with no usable ``X-Forwarded-For``.
    """
    return {"listening": SERVICE.listener is not None, "available": AVAILABILITY.ok, "unavailable_reason": AVAILABILITY.reason, **HEALTH.snapshot()}


@router.post("/public/links", status_code=201, dependencies=STORE_GATE)
async def mint_link(body: MintBody, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Mint a link. Output: {token, link}; the token appears only in this answer."""
    try:
        palette = theme_rules.clean_theme(body.theme)
    except theme_rules.ThemeRefused as exc:
        raise HTTPException(status_code=422, detail={"code": "publicboard_invalid", "detail": str(exc)}) from exc
    try:
        made = await minting.mint_link(ctx, body.board, body.ttl, body.mode, body.revision, access=body.access, theme=palette)
    except minting.MintRefused as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "detail": str(exc), **exc.extra}) from exc
    return {"token": made["token"], "link": made["link"].as_wire()}


@router.get("/public/links", dependencies=STORE_GATE)
async def list_links(board: Optional[str] = Query(None, min_length=1, max_length=200), ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """The links, newest first. Output: {links}."""
    rows = await asyncio.to_thread(links.list_links, ctx.storage, board)
    return {"links": [row.as_wire() for row in rows]}


@router.get("/public/links/{link_id}/token", dependencies=STORE_GATE)
async def copy_link(link_id: str, ctx: CplugContext = Ctx) -> JSONResponse:
    """The kept full token of an ACTIVE link, for the owner's copy key (``no-store``). Output: {token}.

    Raises: 404 publicboard_no_link (unknown); 409 publicboard_link_ended (revoked or expired); 409 publicboard_not_copyable (made before copy was kept).
    """
    link = next((row for row in await asyncio.to_thread(links.list_links, ctx.storage) if row.id == link_id), None)
    if link is None:
        raise HTTPException(status_code=404, detail={"code": "publicboard_no_link", "detail": "no such link"})
    if link.status != "active":
        raise HTTPException(status_code=409, detail={"code": "publicboard_link_ended", "detail": "this link has ended"})
    token = await asyncio.to_thread(links.token_of, ctx.storage, link_id)
    if token is None:
        raise HTTPException(status_code=409, detail={"code": "publicboard_not_copyable", "detail": "made before copy was kept"})
    return JSONResponse({"token": token}, headers={"Cache-Control": "no-store"})


@router.delete("/public/links/{link_id}", dependencies=STORE_GATE)
async def revoke_one(link_id: str, ctx: CplugContext = Ctx) -> Dict[str, int]:
    """Revoke one link. Output: {revoked: 1}. Raises 404 publicboard_no_link."""
    if not await asyncio.to_thread(links.revoke_link, ctx.storage, link_id):
        raise HTTPException(status_code=404, detail={"code": "publicboard_no_link", "detail": "no live link with that id"})
    return {"revoked": 1}


@router.delete("/public/links", dependencies=STORE_GATE)
async def revoke_many(board: Optional[str] = Query(None, min_length=1, max_length=200), all_links: bool = Query(False, alias="all"),
                      ended: bool = Query(False), ctx: CplugContext = Ctx) -> Dict[str, int]:
    """Revoke every live link of one board, or all; with ``ended=true`` (and a board) DELETE the board's ended links, expired and revoked.
    Output: {revoked: n} or, for ``ended``, {cleared: n}. Raises 422 unless exactly one of ``board`` and ``all`` is given, and ``ended`` needs a board."""
    if (board is None) == (not all_links) or (ended and board is None):
        raise HTTPException(status_code=422, detail={"code": "publicboard_invalid", "detail": "give exactly one of board or all=true (ended needs a board)"})
    if ended:
        return {"cleared": await asyncio.to_thread(links.clear_ended, ctx.storage, board or "")}
    count = await asyncio.to_thread(links.revoke_all, ctx.storage) if all_links else await asyncio.to_thread(links.revoke_board, ctx.storage, board or "")
    return {"revoked": count}


@router.get("/public/visitors", dependencies=STORE_GATE)
async def list_visitors(board: str = Query(..., min_length=1, max_length=200), ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """What visitors posted on one board, oldest first, each visitor's answers per revision (the u-revisions), and who is on the page right now. Output: {responses, visitors, present (u numbers viewing), viewing (viewers with no u number yet)}."""
    store = responses.storage_for(ctx.storage.path)
    answers = await asyncio.to_thread(drafts.list_board, store, board)
    here = presence.PRESENCE.present(board, time.monotonic())
    numbered = await asyncio.to_thread(drafts.numbers_of, store, here)
    return {"responses": await asyncio.to_thread(visitors.listing, store, port(), board), "visitors": [row.as_wire() for row in answers],
            "present": sorted(numbered.values()), "viewing": len(here) - len(numbered)}


_REVISION_PATTERN = r"^r[1-9][0-9]{0,5}$"


@router.get("/public/visitors/u/{number}", dependencies=STORE_GATE)
async def visitor_revision(number: int = Path(..., ge=1), board: str = Query(..., min_length=1, max_length=200),
                           revision: str = Query(..., pattern=_REVISION_PATTERN), ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """The answers of one u-revision, for the owner's page that opened it (the listing carries no bodies). Output: {body}.

    Raises 404 publicboard_no_visitor.
    """
    body = await asyncio.to_thread(drafts.revision_body, responses.storage_for(ctx.storage.path), board, number, revision)
    if body is None:
        raise HTTPException(status_code=404, detail={"code": "publicboard_no_visitor", "detail": "no such visitor answers"})
    return {"body": body}


@router.delete("/public/visitors/u/{number}", dependencies=STORE_GATE)
async def remove_visitor_revision(number: int = Path(..., ge=1), board: str = Query(..., min_length=1, max_length=200),
                                  revision: Optional[str] = Query(None, pattern=_REVISION_PATTERN), ctx: CplugContext = Ctx) -> Dict[str, int]:
    """Remove one u-revision (``revision`` given) or the whole visitor ``u<number>`` with every draft of theirs. Output: {removed: drafts removed}."""
    removed = await asyncio.to_thread(drafts.delete_revision, responses.storage_for(ctx.storage.path), board, number, revision)
    if removed:
        announce.changed(ctx, board)
    return {"removed": removed}


@router.post("/public/visitors/forward", dependencies=STORE_GATE)
async def forward_visitors(body: ForwardBody, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Forward the board's new visitor responses to its task as the owner's reply. Output: {forwarded, left, messages, message_id, item_id}."""
    store = responses.storage_for(ctx.storage.path)
    try:
        answer = await visitors.forward(store, port(), body.board, body.ids)
    except visitors.ForwardRefused as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "detail": str(exc)}) from exc
    await asyncio.to_thread(announce.settled, ctx, store, body.board)
    return answer


@router.delete("/public/visitors/{response_id}", dependencies=STORE_GATE)
async def remove_visitor(response_id: int, ctx: CplugContext = Ctx) -> Dict[str, int]:
    """Remove one stored visitor response. Output: {removed: 1}. Raises 404 publicboard_no_response."""
    store = responses.storage_for(ctx.storage.path)
    board = await asyncio.to_thread(responses.board_of, store, response_id)
    if board is None or not await asyncio.to_thread(responses.delete_one, store, response_id):
        raise HTTPException(status_code=404, detail={"code": "publicboard_no_response", "detail": "no visitor response with that id"})
    await asyncio.to_thread(announce.settled, ctx, store, board)
    return {"removed": 1}


@router.delete("/public/visitors", dependencies=STORE_GATE)
async def remove_forwarded(board: str = Query(..., min_length=1, max_length=200), ctx: CplugContext = Ctx) -> Dict[str, int]:
    """Remove every already forwarded visitor response of a board. Output: {removed: n}."""
    removed = await asyncio.to_thread(responses.delete_forwarded, responses.storage_for(ctx.storage.path), board)
    announce.changed(ctx, board)
    return {"removed": removed}
