
from __future__ import annotations

from typing import Any, Dict

from src.cplugs.reviewboard import live, live_send, wire
from src.cplugs.reviewboard.errors import BoardError
from src.cplugs.reviewboard.live_requests import LiveBody, LiveCreateBody, LiveEndBody, LiveSendBody, MilestoneBody
from src.cplugs.reviewboard.routes import Ctx, router
from src.cplugs.sdk import CplugContext


@router.post("/boards/live")
async def start_live_board(body: LiveCreateBody, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Create a board that starts live. Input: body. Output: see the module docstring."""
    try:
        return await live.start_board(ctx, body)
    except BoardError as exc:
        raise wire.http_error(exc) from exc


@router.put("/boards/{slug}/live")
async def overwrite_draft(slug: str, body: LiveBody, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Overwrite a board's working draft. Inputs: slug; body. Output: see the module docstring."""
    try:
        return await live.set_draft(ctx, slug, body)
    except BoardError as exc:
        raise wire.http_error(exc) from exc


@router.post("/boards/{slug}/live/milestone")
async def bookmark_draft(slug: str, body: MilestoneBody, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Freeze the working draft as a named revision. Inputs: slug; body. Output: see the module docstring."""
    try:
        return await live.milestone(ctx, slug, body)
    except BoardError as exc:
        raise wire.http_error(exc) from exc


@router.post("/boards/{slug}/live/end")
async def end_live(slug: str, body: LiveEndBody, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """End the live session. Inputs: slug; body. Output: see the module docstring."""
    try:
        return await live.end(ctx, slug, body)
    except BoardError as exc:
        raise wire.http_error(exc) from exc


@router.post("/boards/{slug}/live/send")
async def send_live(slug: str, body: LiveSendBody, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    try:
        return await live_send.send(ctx, slug, body)
    except BoardError as exc:
        raise wire.http_error(exc) from exc
