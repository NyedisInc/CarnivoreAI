"""A review board's attachment routes, under ``/api/v1/cplugs/reviewboard`` (``docs/reviewboard.md``, "Attachments", #1788).

Registered on ``routes.router`` (this module only adds routes; ``routes.py`` imports it last). Bearer auth and the plugin's switch as
every board route; 409 ``reviewboard_no_root`` while the folder is unusable. Every refusal is ``{code, detail}``.

  GET  /boards/{slug}/attachments   {slug, attachments: [{file_id, item_id, message_id, name, mime, bytes, sha256, added_at, revision,
                                    url}]}, oldest first. ``url`` is the Task Manager's route for that file (same origin, the app's login; None
                                    while the Task Manager is off). 404 ``reviewboard_not_found``. A board that does not validate lists none.
  POST /boards/{slug}/attachments   JSON ``{files: [{name, content_base64}], note?, request_review?}`` (``request_review`` default true):
                                    the same function as ``task_manager_board_attachment_add`` (``attachments.attach``); answers
                                    {slug, attachments: [...the new entries], message_id, review, etag, indexed: true}. When the files
                                    reached the task but the board's index could not be written, still 200 with ``indexed: false``,
                                    ``etag: null`` and a ``warning``: do not retry, the files are on the task. 411
                                    ``reviewboard_length_required`` (no Content-Length), 413 ``reviewboard_too_large`` (a request past
                                    ``attachments.MAX_BODY_BYTES``, more than ``attachments.MAX_FILES`` files or ``attachments.MAX_TOTAL_BYTES``
                                    in all, a board's index full), 422 ``reviewboard_invalid`` (a bad body, a file the upload rule refuses, a
                                    note with a control character or a thread line too long), 404 ``reviewboard_not_found`` /
                                    ``reviewboard_no_task``, 409 ``reviewboard_scratch_board``, ``reviewboard_unlinked``,
                                    ``reviewboard_read_only``, ``reviewboard_no_task_manager``, ``reviewboard_task_manager_refused`` (the task refused
                                    the info; ``task_code`` says why), 500 ``reviewboard_store_failed`` (a file could not be written). A
                                    refusal stores nothing.

Push topic: ``boards`` once per attach (``topics.TOPIC``).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError

from src.cplugs.reviewboard import attachments, wire
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
    """A board's attachments with their open URLs. Input: slug. Output: see the module docstring. Errors: 404, 409."""
    try:
        return await attachments.listing(ctx, slug)
    except BoardError as exc:
        raise wire.http_error(exc) from exc


@router.post("/boards/{slug}/attachments")
async def add_attachments(slug: str, request: Request, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    try:
        body = await _body(request)
        uploads = attachments.decode_inline(body.files)
        return await attachments.attach(ctx, slug, uploads, note=body.note, request_review=body.request_review)
    except BoardError as exc:
        raise wire.http_error(exc) from exc
