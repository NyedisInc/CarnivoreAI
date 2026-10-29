
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.auth import require_auth
from src.api.catalog_hosted_routes import _hosted, _relay, _state_dir
from src.api.catalog_rating_routes import _bearer
from src.core.catalog import catalog_auth
from src.models.catalog_account import (
    CatalogDeleteRequest,
    CatalogHandleRequest,
    CatalogNewsRequest,
    CatalogRegisterRequest,
    CatalogRevokeResponse,
    CatalogSessionsResponse,
)

router = APIRouter(tags=["catalog"])

_SID_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")


@router.get(
    "/catalog/account/sessions",
    response_model=CatalogSessionsResponse,
    dependencies=[Depends(require_auth)],
)
async def catalog_account_sessions(request: Request) -> CatalogSessionsResponse:
    """Every device signed in to this catalog account, newest first."""
    answer = await _hosted(request, "GET", "/auth/sessions", bearer=await _bearer(request))
    return CatalogSessionsResponse(**_relay(answer))


@router.delete(
    "/catalog/account/sessions/{sid}",
    response_model=CatalogRevokeResponse,
    dependencies=[Depends(require_auth)],
)
async def catalog_account_revoke_session(request: Request, sid: str) -> CatalogRevokeResponse:
    """Sign one device out of the catalog account (its next request is refused)."""
    if not 8 <= len(sid) <= 32 or not set(sid) <= _SID_CHARS:
        raise HTTPException(
            status_code=400,
            detail={"code": "bad_session_id", "detail": "that is not a session id"},
        )
    answer = await _hosted(
        request, "DELETE", f"/auth/sessions/{sid}", bearer=await _bearer(request)
    )
    return CatalogRevokeResponse(**_relay(answer))


@router.post(
    "/catalog/account/sessions/revoke-others",
    response_model=CatalogRevokeResponse,
    dependencies=[Depends(require_auth)],
)
async def catalog_account_revoke_others(request: Request) -> CatalogRevokeResponse:
    """Sign every OTHER device out of the catalog account; this one stays."""
    answer = await _hosted(
        request, "POST", "/auth/sessions/revoke-all", bearer=await _bearer(request)
    )
    return CatalogRevokeResponse(**_relay(answer))


@router.post("/catalog/account/register", dependencies=[Depends(require_auth)])
async def catalog_account_register(
    request: Request, body: CatalogRegisterRequest
) -> Dict[str, Any]:
    """Register the catalog account: terms, the 16-or-older attestation, a handle."""
    answer = await _hosted(
        request,
        "POST",
        "/register",
        json_body=body.model_dump(exclude_none=True),
        bearer=await _bearer(request),
    )
    return _relay(answer)


@router.post("/catalog/account/handle", dependencies=[Depends(require_auth)])
async def catalog_account_handle(request: Request, body: CatalogHandleRequest) -> Dict[str, Any]:
    """Rename the catalog account's own handle (host: `POST /v1/account/handle`).

    The host enforces every rule (shape, reserved names, lookalikes, the publisher
    lock, one change per 30 days, the 90 day hold of the old handle) and its
    refusal codes pass through unchanged.
    """
    answer = await _hosted(
        request, "POST", "/account/handle", json_body=body.model_dump(), bearer=await _bearer(request)
    )
    return _relay(answer)


@router.post("/catalog/account/news", dependencies=[Depends(require_auth)])
async def catalog_account_news(request: Request, body: CatalogNewsRequest) -> Dict[str, Any]:
    """Turn the news email on or off (host: `POST /v1/account/news`); answers `{"news_opt_in": bool}`."""
    answer = await _hosted(
        request, "POST", "/account/news", json_body=body.model_dump(), bearer=await _bearer(request)
    )
    return _relay(answer)


@router.post("/catalog/account/delete", dependencies=[Depends(require_auth)])
async def catalog_account_delete(request: Request, body: CatalogDeleteRequest) -> Dict[str, Any]:
    """Delete the catalog account: needs a sign in within 15 minutes and the handle typed exactly.

    A guest account may delete itself (it confirms with the word ``delete``; the host decides).
    """
    answer = await _hosted(
        request, "POST", "/account/delete", json_body=body.model_dump(), bearer=await _bearer(request, allow_guest=True)
    )
    result = _relay(answer)
    catalog_auth.forget(_state_dir(request))
    return result


@router.get("/catalog/account/export", dependencies=[Depends(require_auth)])
async def catalog_account_export(request: Request) -> Dict[str, Any]:
    """Everything the catalog account owns (a guest account included), as the host's JSON export document."""
    answer = await _hosted(request, "GET", "/account/export", bearer=await _bearer(request, allow_guest=True))
    return _relay(answer)
