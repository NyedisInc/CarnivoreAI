
from __future__ import annotations

from typing import Any, Optional, Tuple

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.core.notify_caps import act as act_mod
from src.core.notify_caps.limiter import LIMITER
from src.api.capped_reads import read_capped_body
from src.core.notify_caps.store import HEADER_NAME, CapRecord, get_store
from src.core.notify_caps.verify import verify
from src.core.notify_media import store as media_store
from src.models.dialogs import OTHER_MAX_CHARS

logger = structlog.get_logger()
router = APIRouter(prefix="/notify", tags=["notify"])
_NO_STORE = {"Cache-Control": "no-store"}
MAX_BODY_BYTES = 4096 + 4 * OTHER_MAX_CHARS


class ActBody(BaseModel):
    """``POST /notify/act`` body. Unknown fields are a 422."""

    model_config = ConfigDict(extra="forbid")

    action: str = Field(min_length=1, max_length=40)
    text: Optional[str] = Field(default=None, max_length=OTHER_MAX_CHARS)


def _reply(status: int, body: dict) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers=_NO_STORE)


def _address(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _miss(address: str, status: int, body: dict) -> JSONResponse:
    if status != 404:
        return _reply(status, body)
    if LIMITER.blocked(address):
        return _reply(429, {"error": "too_many_misses"})
    LIMITER.miss(address)
    logger.info("notify_cap_miss")
    return _reply(404, body)


def _authorize(request: Request) -> Tuple[Optional[CapRecord], Optional[JSONResponse]]:
    record, refused = verify(get_store(), request.app.state, request.headers.get(HEADER_NAME))
    if record is None:
        return None, _miss(_address(request), *refused)  # type: ignore[misc]
    return record, None


@router.post("/act")
async def post_act(request: Request) -> JSONResponse:
    """Answer the notification the capability names, once. Statuses: plan 2.5.

    The body is parsed here, not by FastAPI, because the app turns every body validation error into a 400 that echoes
    the input; this route answers 422 ``{"error": "bad_action"}`` for any body that is not ``{action, text?}``.

    Example: POST /api/v1/notify/act  X-Carnivore-Cap: <cap>  {"action": "opt.2"}
    """
    try:
        raw = await read_capped_body(request, MAX_BODY_BYTES, "request")
    except HTTPException:
        return _reply(413, {"error": "too_large"})
    try:
        body = ActBody.model_validate_json(raw)
    except (ValueError, ValidationError):
        return _reply(422, {"error": "bad_action"})
    cap = request.headers.get(HEADER_NAME) or ""
    status, answer = await act_mod.act(get_store(), request.app.state, cap, body.action, body.text)
    return _miss(_address(request), status, answer)


@router.get("/card")
async def get_card(request: Request) -> JSONResponse:
    """The full card JSON for the capability's notification (64 KB at most)."""
    record, refused = _authorize(request)
    return refused if record is None else _reply(200, record.card)  # type: ignore[return-value]


def _media(request: Request, media_id: str, poster: bool) -> Response:
    record, refused = _authorize(request)
    if record is None:
        return refused  # type: ignore[return-value]
    found = media_store.entry(media_id) if media_id in record.media_ids else None
    path = (found.poster if poster else found.path) if found is not None else None
    if found is None or path is None:
        return _miss(_address(request), 404, {"error": "not_found"})
    headers: Any = {**_NO_STORE, "X-Content-Type-Options": "nosniff"}
    return FileResponse(path, media_type="image/png" if poster else found.mime, headers=headers, filename=media_id, content_disposition_type="attachment")


@router.get("/media/{media_id}")
async def get_media(request: Request, media_id: str) -> Response:
    """The attachment bytes, with its stored mime."""
    return _media(request, media_id, poster=False)


@router.get("/media/{media_id}/poster")
async def get_media_poster(request: Request, media_id: str) -> Response:
    """The attachment's poster PNG (a video frame or a PDF first page)."""
    return _media(request, media_id, poster=True)
