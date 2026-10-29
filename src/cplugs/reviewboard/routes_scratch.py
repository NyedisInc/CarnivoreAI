
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import Request, UploadFile

from src.cplugs.reviewboard import scratch, wire
from src.cplugs.reviewboard.errors import BadRequest, BoardError, LengthRequired, TooLarge
from src.cplugs.reviewboard.routes import Ctx, router
from src.cplugs.reviewboard.schema import MAX_VIEW_BYTES
from src.cplugs.sdk import CplugContext
from src.cplugs.sdk.uploads import caps, is_form_file

MAX_REQUEST_BYTES = scratch.MAX_TOTAL_BYTES + MAX_VIEW_BYTES + 1024 * 1024
_CHUNK = 1024 * 1024
_MAX_FIELDS = 8
_MAX_FIELD_BYTES = 8 * 1024


async def _read_part(part: UploadFile, limit: int, what: str) -> bytes:
    chunks: List[bytes] = []
    size = 0
    while True:
        chunk = await part.read(_CHUNK)
        if not chunk:
            return b"".join(chunks)
        size += len(chunk)
        if size > limit:
            raise TooLarge(f"{what} is over {limit} bytes")
        chunks.append(chunk)


def _field(form: Any, key: str) -> Optional[str]:
    value = form.get(key)
    if value is None or isinstance(value, str):
        return value
    raise BadRequest(f"{key} must be a text field, not a file")


def _viewport(text: Optional[str]) -> Optional[int]:
    if text is None or text == "":
        return None
    if not text.isdigit():
        raise BadRequest("viewport must be a width in CSS px")
    return int(text)


@router.post("/scratch")
async def post_scratch(request: Request, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Post a page and its files to a scratch board, as the owner. Output: see the module docstring.

    The size is judged from ``Content-Length`` BEFORE the body is parsed (a request without one is refused 411: the server then reads
    no more than it declared), and the parser itself is bounded (``max_files``, ``max_fields``, ``max_part_size`` for text fields; Starlette answers 400 past one).
    """
    try:
        declared = request.headers.get("content-length", "")
        if not declared.isdigit():
            raise LengthRequired("a scratch post must declare its Content-Length")
        if int(declared) > MAX_REQUEST_BYTES:
            raise TooLarge(f"the request is over {MAX_REQUEST_BYTES} bytes")
        async with request.form(max_files=scratch.MAX_FILES + 1, max_fields=_MAX_FIELDS, max_part_size=_MAX_FIELD_BYTES) as form:
            parts = form.getlist("files")
            page = form.get("page")
            if not is_form_file(page):
                raise BadRequest("page is required: the HTML page as a file part")
            if len(parts) > scratch.MAX_FILES:
                raise TooLarge(f"a scratch post carries at most {scratch.MAX_FILES} files, not {len(parts)}")
            if any(not is_form_file(p) for p in parts):
                raise BadRequest("files must be file parts")
            per_file = min(max(caps()), scratch.MAX_TOTAL_BYTES)
            uploads = [scratch.Upload(p.filename or "", await _read_part(p, per_file, p.filename or "a file")) for p in parts]
            try:
                html = (await _read_part(page, MAX_VIEW_BYTES, "the page")).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise BadRequest("the page must be UTF-8 text") from exc
            name = _field(form, "name")
            if not name:
                raise BadRequest("name is required")
            post = scratch.ScratchPost(name=name, html=html, title=_field(form, "title"), summary=_field(form, "summary"),
                                       viewport=_viewport(_field(form, "viewport")), files=uploads)
        return await scratch.post(ctx, post)
    except BoardError as exc:
        raise wire.http_error(exc) from exc


@router.delete("/boards/{slug}")
async def clear_scratch(slug: str, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Clear a scratch board for good. Input: slug. Output: {slug, revisions, files, bytes}. Errors: 404, 409 reviewboard_not_scratch."""
    try:
        return await scratch.clear(ctx, slug)
    except BoardError as exc:
        raise wire.http_error(exc) from exc
