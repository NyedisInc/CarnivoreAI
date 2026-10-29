
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError

from src.cplugs.reviewboard import attachment_removal, attachments, wire
from src.cplugs.reviewboard.errors import BadRequest, BoardError, LengthRequired, TooLarge
from src.cplugs.reviewboard.routes import Ctx, router
from src.cplugs.sdk import CplugContext


class AttachBody(BaseModel):
    """The POST body. Fields: files (``{name, content_base64}`` each, checked by ``attachments.decode_inline``); note; request_review."""

    model_config = ConfigDict(extra="forbid")
    files: List[Any] = Field(min_length=1, max_length=attachments.MAX_FILES)
    note: Optional[str] = Field(default=None, max_length=attachments.MAX_NOTE)
    request_review: StrictBool = True


async def _body(request: Request) -> AttachBody:
    declared = request.headers.get("content-length", "")
    if not declared.isdigit():
        raise LengthRequired("an attach must declare its Content-Length")
    if int(declared) > attachments.MAX_BODY_BYTES:
        raise TooLarge(f"the request is over {attachments.MAX_BODY_BYTES} bytes")
    try:
        return AttachBody.model_validate(json.loads(await request.body()))
    except ValueError as exc:
        shown = "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'body'}: {e['msg']}" for e in exc.errors()[:5]) \
            if isinstance(exc, ValidationError) else "the body must be JSON"
        raise BadRequest(shown) from exc


@router.get("/boards/{slug}/attachments")
async def list_attachments(slug: str, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """A board's attachments with their open URLs, and its removed ones. Input: slug. Output: see the module docstring. Errors: 404, 409."""
    try:
        return await attachments.listing(ctx, slug)
    except BoardError as exc:
        raise wire.http_error(exc) from exc


@router.post("/boards/{slug}/attachments")
async def add_attachments(slug: str, request: Request, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Attach files to a board, as the owner. Inputs: slug; the JSON body. Output: see the module docstring."""
    try:
        body = await _body(request)
        uploads = attachments.decode_inline(body.files)
        return await attachments.attach(ctx, slug, uploads, note=body.note, request_review=body.request_review)
    except BoardError as exc:
        raise wire.http_error(exc) from exc


@router.delete("/boards/{slug}/attachments/{file_id}")
async def remove_attachment(slug: str, file_id: str, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Remove one attachment from a board, as the owner (its entry becomes a tombstone). Inputs: slug; file_id. Output: see the module docstring."""
    try:
        return await attachment_removal.remove(ctx, slug, file_id)
    except BoardError as exc:
        raise wire.http_error(exc) from exc
