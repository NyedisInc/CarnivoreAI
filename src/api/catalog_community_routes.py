
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.auth import require_auth
from src.api.catalog_hosted_routes import _hosted, _relay, _safe_item_id
from src.api.catalog_rating_routes import _bearer
from src.models.catalog_community import CommentPageResponse, ProfileResponse

router = APIRouter(tags=["catalog"])

SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def safe_segment(value: str, code: str = "bad_request") -> str:
    if not SAFE_SEGMENT.match(value) or ".." in value:
        raise HTTPException(
            status_code=400, detail={"code": code, "detail": "that is not a valid id"}
        )
    return value


def cursor_query(cursor: Optional[str], **extra: Optional[str]) -> str:
    pairs = {"item_id": extra.get("item_id"), "cursor": cursor}
    parts = [f"{k}={quote(v, safe='')}" for k, v in pairs.items() if v]
    return "?" + "&".join(parts) if parts else ""


@router.get(
    "/catalog/items/{item_id:path}/comments",
    response_model=CommentPageResponse,
    dependencies=[Depends(require_auth)],
)
async def catalog_get_comments(
    request: Request, item_id: str, cursor: Optional[str] = None
) -> CommentPageResponse:
    """One page (50) of an item's comment thread, oldest first. Works signed out.

    No bearer is sent: the thread is public, so this read never spends or
    rotates a credential. A removed or deleted comment with replies comes
    back as a ``placeholder``.

    Raises: 400 ``bad_item_id`` / ``bad_cursor``; 404 ``unknown_item``
    (relayed); 502 when the hosted api cannot be reached.
    """
    safe = _safe_item_id(item_id)
    answer = await _hosted(
        request, "GET", f"/items/{safe}/comments{cursor_query(cursor)}"
    )
    return CommentPageResponse(**_relay(answer))


@router.get(
    "/catalog/me/comments",
    response_model=CommentPageResponse,
    dependencies=[Depends(require_auth)],
)
async def catalog_get_my_comments(
    request: Request, item_id: Optional[str] = None, cursor: Optional[str] = None
) -> CommentPageResponse:
    """Your own comments, newest first, every status but deleted.

    The only route that returns the text of a held or hidden comment, and
    only to its author. Needs a catalog sign in: signed out is a 403
    ``unauthorized`` with nothing sent upstream.

    Raises: 400 ``bad_item_id``; 403 ``unauthorized``; 502 unreachable.
    """
    safe = _safe_item_id(item_id) if item_id else None
    bearer = await _bearer(request)
    answer = await _hosted(
        request, "GET", f"/me/comments{cursor_query(cursor, item_id=safe)}", bearer=bearer
    )
    return CommentPageResponse(**_relay(answer))


@router.get(
    "/catalog/profiles/{handle}",
    response_model=ProfileResponse,
    dependencies=[Depends(require_auth)],
)
async def catalog_get_profile(request: Request, handle: str) -> ProfileResponse:
    """A public profile: handle, join date, bio, links, published items. Works signed out.

    Raises: 400 ``bad_request`` for a malformed handle; 404 ``not_found``
    (relayed; unknown and disabled accounts answer the same); 502.
    """
    answer = await _hosted(request, "GET", f"/profiles/{safe_segment(handle)}")
    return ProfileResponse(**_relay(answer))
