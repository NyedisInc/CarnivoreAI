
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Request

from src.api.auth import require_auth
from src.api.catalog_hosted_routes import _hosted, _relay, _safe_item_id
from src.api.catalog_rating_routes import _bearer
from src.models.catalog_notes import NoteSentResponse, NoteWriteRequest

logger = structlog.get_logger()

router = APIRouter(tags=["catalog"])


@router.post(
    "/catalog/items/{item_id:path}/note",
    response_model=NoteSentResponse,
    status_code=201,
    dependencies=[Depends(require_auth)],
)
async def catalog_send_note(
    request: Request, item_id: str, body: NoteWriteRequest
) -> NoteSentResponse:
    """Send this account's private note about one catalog item.

    THE ONE WRITE THIS ROUTE MAKES. It reaches the same reserved bundled
    ids the ratings proxy accepts (``bundled/<theme_id>``) with no change
    here - the id grammar this app checks is only the traversal guard,
    and deciding whose ids are known stays the hosted api's job. The note
    is stored in a private admin inbox and is never public: nothing this
    app does afterwards can show it again, because the answer carries no
    text back.

    Raises:
        HTTPException(400): ``bad_item_id`` from the traversal guard, or
            a relayed ``bad_request`` / ``empty_note`` / ``note_too_long``
            from the hosted api.
        HTTPException(403): ``unauthorized`` - nothing usable is signed
            in to the catalog here, or the token rotation was refused.
            NOTHING IS SENT UPSTREAM in that case.
        HTTPException(403): relayed ``account_disabled`` / ``forbidden``.
        HTTPException(404): relayed ``unknown_item``.
        HTTPException(429): relayed ``rate_limited`` - today's ten notes
            for this account are gone.
        HTTPException(502): the hosted api could not be reached. NEVER a
            201: a note that was not recorded must not report that it
            was sent.
    """
    safe = _safe_item_id(item_id)
    bearer = await _bearer(request)
    answer = await _hosted(
        request,
        "POST",
        f"/items/{safe}/note",
        json_body={"text": body.text},
        bearer=bearer,
    )
    relayed = _relay(answer)
    return NoteSentResponse(
        item_id=relayed.get("item_id"), created_at=relayed.get("created_at")
    )
