
from __future__ import annotations

from typing import Any, Dict

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.auth import require_auth
from src.api.catalog_client_status import CATALOG_SIGNED_OUT_STATUS, client_status
from src.api.catalog_hosted_routes import (
    _catalog,
    _hosted,
    _relay,
    _safe_item_id,
    _state_dir,
)
from src.core.catalog import catalog_auth, hosted_api
from src.models.catalog_ratings import ItemRatingWriteResponse, RatingWriteRequest

logger = structlog.get_logger()

router = APIRouter(tags=["catalog"])


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=CATALOG_SIGNED_OUT_STATUS,
        detail={
            "code": "unauthorized",
            "detail": "this machine is not signed in to the catalog",
        },
    )


async def _bearer(request: Request, allow_guest: bool = False) -> str:
    try:
        return await catalog_auth.bearer(
            _state_dir(request), _catalog(request).api_base_url(), allow_guest=allow_guest
        )
    except catalog_auth.SignedOut:
        raise _unauthorized() from None
    except catalog_auth.RotationFailed as exc:
        raise HTTPException(status_code=client_status(exc.status), detail=exc.body) from exc
    except hosted_api.HostedUnavailable as exc:
        raise HTTPException(
            status_code=502, detail={"code": exc.code, "detail": exc.detail}
        ) from exc


def _safe_stars(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "bad_request",
                "detail": "stars must be an integer from 1 to 5",
            },
        )
    return value


def _write_view(body: Dict[str, Any]) -> ItemRatingWriteResponse:
    return ItemRatingWriteResponse(
        item_id=body.get("item_id"),
        count=body.get("count"),
        average=body.get("average"),
        histogram=body.get("histogram"),
        your_stars=body.get("your_stars"),
        removed=body.get("removed"),
    )


@router.put(
    "/catalog/items/{item_id:path}/rating",
    response_model=ItemRatingWriteResponse,
    dependencies=[Depends(require_auth)],
)
async def catalog_put_rating(
    request: Request, item_id: str, body: RatingWriteRequest
) -> ItemRatingWriteResponse:
    """Record this account's rating of one item.

    **THE FIRST WRITE THIS APP SENDS THE CATALOG.** It carries the bearer
    token out of the 0600 store, rotating it first when it has expired;
    see :func:`_bearer`.

    **THE BODY IS CHECKED BEFORE THE CREDENTIAL IS SPENT.** The id guard
    and the stars guard both run before :func:`_bearer`, so a malformed
    call never costs a rotation and never reaches the catalog host.

    The answer is the POST-WRITE summary, so a screen repaints from what
    is stored rather than from what it hoped. It carries no ``reviews``
    key, which is upstream's decision; the block re-reads for those.

    Raises:
        HTTPException(400): ``bad_item_id``, or ``bad_request`` for a
            stars value this server will not forward.
        HTTPException(403): ``unauthorized`` - nothing usable is signed
            in here, or the rotation was refused. NOTHING IS SENT
            UPSTREAM in that case.
        HTTPException(404): relayed ``unknown_item``.
        HTTPException(429): relayed ``rate_limited`` - the account's
            fifty votes for this UTC day are gone.
        HTTPException(502): the hosted api could not be reached. NEVER a
            200: a rating that was not recorded must not report that it
            was.
    """
    safe = _safe_item_id(item_id)
    stars = _safe_stars(body.stars)
    bearer = await _bearer(request, allow_guest=True)
    answer = await _hosted(
        request,
        "PUT",
        f"/items/{safe}/rating",
        json_body={"stars": stars, "text": body.text or ""},
        bearer=bearer,
    )
    return _write_view(_relay(answer))


@router.delete(
    "/catalog/items/{item_id:path}/rating",
    response_model=ItemRatingWriteResponse,
    dependencies=[Depends(require_auth)],
)
async def catalog_delete_rating(
    request: Request, item_id: str
) -> ItemRatingWriteResponse:
    """Withdraw this account's rating of one item.

    WITHDRAWING IS A WRITE AND IS HELD TO THE SAME GATE, because it
    changes an item's public totals exactly as giving one does. It does
    NOT spend a vote upstream: the daily limit bounds how much one
    account can influence a score, and putting the totals back where they
    were is not influence.

    Raises:
        HTTPException(400): ``bad_item_id``.
        HTTPException(403): ``unauthorized``, with nothing sent upstream.
        HTTPException(404): relayed ``unknown_item``.
        HTTPException(502): the hosted api could not be reached.
    """
    safe = _safe_item_id(item_id)
    bearer = await _bearer(request, allow_guest=True)
    answer = await _hosted(
        request, "DELETE", f"/items/{safe}/rating", bearer=bearer
    )
    return _write_view(_relay(answer))
