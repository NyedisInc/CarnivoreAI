
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from src.api.auth import require_auth
from src.api.catalog_client_status import client_status
from src.core.catalog import catalog_auth, hosted_api, token_refresh
from src.core.catalog.device_label import device_fields
from src.core.catalog.device_flow import DeviceFlowStore
from src.core.db import get_meta
from src.core.db_models import META_INSTALL_ID
from src.models.catalog_installs import (
    InstallCountEntry,
    InstallCountsRequest,
    InstallCountsResponse,
    ItemInstallsResponse,
)
from src.models.catalog_ratings import ItemRatingsResponse, RatingReview
from src.models.catalog_signin import (
    CatalogSessionResponse,
    DevicePollRequest,
    DeviceStartResponse,
)

logger = structlog.get_logger()

router = APIRouter(tags=["catalog"])

_flows = DeviceFlowStore()

_UNSAFE_SEGMENTS = frozenset({"", ".", ".."})


def _catalog(request: Request):
    return request.app.state.services.catalog


def install_id(request: Request) -> str:
    try:
        with closing(_catalog(request).open_db()) as conn:
            return get_meta(conn, META_INSTALL_ID) or ""
    except sqlite3.Error as exc:
        logger.warning("catalog_install_id_unreadable", error=str(exc))
        return ""


def _state_dir(request: Request) -> Path:
    return request.app.state.services.settings_reader.state_dir()


def _relay(answer: hosted_api.HostedAnswer) -> Dict[str, Any]:
    if answer.status >= 400:
        raise HTTPException(
            status_code=client_status(answer.status), detail=dict(answer.body)
        )
    return answer.body


async def _hosted(
    request: Request,
    method: str,
    path: str,
    *,
    json_body: Optional[Dict[str, Any]] = None,
    bearer: Optional[str] = None,
) -> hosted_api.HostedAnswer:
    base_url = _catalog(request).api_base_url()
    try:
        answer = await hosted_api.call(
            base_url, method, path, json_body=json_body, bearer=bearer
        )
    except hosted_api.HostedUnavailable as exc:
        raise HTTPException(
            status_code=502, detail={"code": exc.code, "detail": exc.detail}
        ) from exc
    if bearer and token_refresh.is_session_revoked(answer.status, answer.body):
        catalog_auth.forget_if_access_is(_state_dir(request), bearer)
        logger.info("catalog_session_revoked_upstream")
    return answer


def _safe_item_id(item_id: str) -> str:
    segments = item_id.split("/")
    if not item_id or any(segment in _UNSAFE_SEGMENTS for segment in segments):
        raise HTTPException(
            status_code=400,
            detail={"code": "bad_item_id", "detail": "that is not a valid item id"},
        )
    return item_id


def _reviews_of(body: Dict[str, Any]) -> Optional[list]:
    raw = body.get("reviews")
    if not isinstance(raw, list):
        return None
    return [
        RatingReview(**{key: row[key] for key in RatingReview.model_fields if key in row})
        for row in raw
        if isinstance(row, dict)
    ]


@router.get(
    "/catalog/items/{item_id:path}/ratings",
    response_model=ItemRatingsResponse,
    response_model_exclude_unset=True,
    dependencies=[Depends(require_auth)],
)
async def catalog_item_ratings(request: Request, item_id: str) -> ItemRatingsResponse:
    """What people rated one item, relayed from the hosted api.

    PUBLIC UPSTREAM, so no bearer is sent and nobody has to be signed in
    to read it. The app's own ``require_auth`` still applies, because
    this is one of this server's routes like any other.

    The body is passed through field for field. Nothing is reshaped and
    nothing is defaulted: see :func:`_reviews_of`.

    Raises:
        HTTPException(400): the id would traverse out of the items path.
        HTTPException(502): the hosted api could not be reached.
        HTTPException: the host's own status, for its own refusal.
    """
    safe = _safe_item_id(item_id)
    answer = await _hosted(request, "GET", f"/items/{safe}/ratings")
    body = _relay(answer)
    return ItemRatingsResponse(
        item_id=body.get("item_id"),
        count=body.get("count"),
        average=body.get("average"),
        histogram=body.get("histogram"),
        reviews=_reviews_of(body),
    )


def _by_version_of(body: Dict[str, Any]) -> Optional[Dict[str, int]]:
    raw = body.get("by_version")
    if not isinstance(raw, dict):
        return None
    counts: Dict[str, int] = {}
    for version, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        counts[str(version)] = int(value)
    return counts


@router.get(
    "/catalog/items/{item_id:path}/installs",
    response_model=ItemInstallsResponse,
    dependencies=[Depends(require_auth)],
)
async def catalog_item_installs(request: Request, item_id: str) -> ItemInstallsResponse:
    """How many people reported installing one item, and at which versions.

    PUBLIC UPSTREAM, so no bearer is sent and nobody has to be signed in
    to read it. A read of one already-aggregated row carries no identity,
    which is why the hosted api asks for no token; the app's own
    ``require_auth`` still applies, because this is one of this server's
    routes like any other.

    The install report is not here: it is a background send from
    ``src/core/catalog/install_reporter.py``, always on, under the account or guest account.

    The body is passed through field for field. Nothing is reshaped and
    nothing is defaulted: see :func:`_by_version_of`.

    Raises:
        HTTPException(400): the id would traverse out of the items path.
        HTTPException(404): relayed ``unknown_item`` - the published
            index does not carry that id.
        HTTPException(502): the hosted api could not be reached. NEVER a
            200 carrying zeros: reporting an outage as "nobody has
            installed this" is the failure this layer exists to prevent.
        HTTPException: the host's own status, for its own refusal.
    """
    safe = _safe_item_id(item_id)
    answer = await _hosted(request, "GET", f"/items/{safe}/installs")
    body = _relay(answer)
    return ItemInstallsResponse(
        item_id=body.get("item_id"),
        count=body.get("count"),
        by_version=_by_version_of(body),
    )


_INSTALL_COUNTS_CHUNK = 200


def _install_counts_of(body: Dict[str, Any], asked: set) -> Dict[str, InstallCountEntry]:
    raw = body.get("items")
    if not isinstance(raw, dict):
        return {}
    found: Dict[str, InstallCountEntry] = {}
    for item_id, entry in raw.items():
        count = entry.get("count") if isinstance(entry, dict) else None
        if item_id not in asked or isinstance(count, bool) or not isinstance(count, int):
            continue
        found[item_id] = InstallCountEntry(count=count, by_version=_by_version_of(entry))
    return found


@router.post(
    "/catalog/install-counts",
    response_model=InstallCountsResponse,
    dependencies=[Depends(require_auth)],
)
async def catalog_install_counts(
    request: Request, payload: InstallCountsRequest
) -> InstallCountsResponse:
    """Install counts for many items in as few hosted calls as possible.

    Replaces one ``GET /catalog/items/{id}/installs`` per item on a page
    load, which flooded the hosted api. Same rules as that route: public
    upstream (no bearer), nothing defaulted, a failure never a zero.

    Ids are validated like the per item route, de-duplicated, split into
    chunks of 200 and sent to the hosted ``POST /install-counts``
    sequentially. ONE CHUNK FAILING while another succeeds still answers
    200 with what was read (its ids are simply absent); EVERY chunk
    failing answers as the per item route does.

    Inputs: payload (InstallCountsRequest) - 1 to 1000 item ids.
    Output: InstallCountsResponse - id to {count, by_version}, measured ids only.
    Example: POST {"ids": ["example-owner/sme"]} -> {"items": {"example-owner/sme": {"count": 2, "by_version": {"1.0.0": 2}}}}

    Raises:
        HTTPException(400): an id would traverse out of the items path.
        HTTPException(502): the hosted api could not be reached for any chunk.
        HTTPException: the host's own status, when every chunk was refused.
    """
    ids = list(dict.fromkeys(_safe_item_id(item_id) for item_id in payload.ids))
    items: Dict[str, InstallCountEntry] = {}
    failure: Optional[HTTPException] = None
    succeeded = False
    for start in range(0, len(ids), _INSTALL_COUNTS_CHUNK):
        chunk = ids[start : start + _INSTALL_COUNTS_CHUNK]
        try:
            answer = await _hosted(
                request, "POST", "/install-counts", json_body={"ids": chunk}
            )
            body = _relay(answer)
        except HTTPException as exc:
            failure = failure or exc
            logger.warning("catalog_install_counts_chunk_failed", status=exc.status_code)
            continue
        succeeded = True
        items.update(_install_counts_of(body, set(chunk)))
    if failure is not None and not succeeded:
        raise failure
    return InstallCountsResponse(items=items)


def _required_string(body: Dict[str, Any], key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value:
        raise HTTPException(
            status_code=502,
            detail={
                "code": hosted_api.UNAVAILABLE,
                "detail": f"the catalog api opened a sign in with no {key}",
            },
        )
    return value


def _seconds(body: Dict[str, Any], key: str, fallback: int) -> int:
    value = body.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return fallback
    return max(int(value), 0) or fallback


@router.post(
    "/catalog/auth/device/start",
    response_model=DeviceStartResponse,
    dependencies=[Depends(require_auth)],
)
async def catalog_device_start(request: Request) -> DeviceStartResponse:
    """Open a GitHub device flow and hand back what a person must read.

    **THE DEVICE CODE STAYS ON THIS SERVER.** GitHub answers with two
    strings: the short user code a person types on github.com, and the
    device code the poll exchanges for a token. Only the first is
    returned. The second is held in memory against a random flow id, so a
    page that somebody else reads carries nothing they could finish this
    sign in with.

    Raises:
        HTTPException(502): the hosted api could not be reached, or
            opened a flow with no code in it.
        HTTPException(503): ``auth_not_configured``, which is the live
            state until the GitHub App exists. Relayed with its code so
            the screen can say precisely that.
    """
    return await open_device_flow(request, "/auth/device/start")


async def open_device_flow(
    request: Request, path: str, json_body: Optional[Dict[str, Any]] = None
) -> DeviceStartResponse:
    answer = await _hosted(request, "POST", path, json_body=json_body)
    body = _relay(answer)
    flow_id = _flows.start(
        device_code=_required_string(body, "device_code"),
        expires_in=_seconds(body, "expires_in", 900),
        interval=_seconds(body, "interval", 5),
    )
    return DeviceStartResponse(
        flow_id=flow_id,
        user_code=_required_string(body, "user_code"),
        verification_uri=_required_string(body, "verification_uri"),
        interval=_seconds(body, "interval", 5),
        expires_in=_seconds(body, "expires_in", 900),
    )


@router.post(
    "/catalog/auth/device/poll",
    response_model=CatalogSessionResponse,
    dependencies=[Depends(require_auth)],
)
async def catalog_device_poll(
    request: Request, body: DevicePollRequest
) -> CatalogSessionResponse:
    """Ask whether the person has finished, and store the token if they have.

    **A 428 IS NOT A FAILURE.** The hosted api answers 428
    ``authorization_pending`` or ``slow_down`` while the person has not
    finished, carrying the interval to wait. That is relayed whole, and
    the client keeps polling; treating it as an error would end a sign in
    that is working.

    **WHAT COMES BACK IS A NAME, NEVER A TOKEN.** The access and refresh
    tokens are written to the 0600 store described in
    ``src/core/catalog/token_store.py`` and never leave this server.

    Raises:
        HTTPException(400): ``unknown_flow`` - no such flow, or it
            expired, or it was already exchanged. One refusal covers all
            three deliberately; see ``device_flow.code_for``.
        HTTPException(428): relayed, meaning keep waiting.
        HTTPException(502): the hosted api could not be reached, or
            authorized a sign in with no token in it.
    """
    return await finish_device_flow(request, body, "/auth/device/poll")


async def finish_device_flow(
    request: Request, body: DevicePollRequest, path: str, provider: str = "github"
) -> CatalogSessionResponse:
    device_code = _flows.code_for(body.flow_id)
    if device_code is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unknown_flow",
                "detail": "that sign in is not in progress on this server",
            },
        )
    answer = await _hosted(
        request,
        "POST",
        path,
        json_body={"device_code": device_code, **device_fields()},
    )
    hosted_body = _relay(answer)

    _required_string(hosted_body, "login")
    _required_string(hosted_body, "access_token")
    _required_string(hosted_body, "refresh_token")
    session = catalog_auth.save_session(_state_dir(request), hosted_body, provider)
    _flows.finish(body.flow_id)
    return CatalogSessionResponse.held(session.login)


@router.get(
    "/catalog/auth/session",
    response_model=CatalogSessionResponse,
    dependencies=[Depends(require_auth)],
)
async def catalog_auth_session(request: Request) -> CatalogSessionResponse:
    """Whether this machine is signed in to the catalog, and as whom.

    A LOCAL READ unless the access token is spent: then the shared rotator
    (``catalog_auth``) exchanges it once, and an unreachable host never
    reads as signed out because the sign in lives as long as the 30 day
    refresh token does.

    ONLY AN UNUSABLE REFRESH TOKEN READS AS SIGNED OUT. The reply also
    carries the stored provider and the account email.
    """
    held = await catalog_auth.current(
        _state_dir(request), _catalog(request).api_base_url(), allow_guest=True
    )
    if held is None:
        return CatalogSessionResponse(signed_in=False, login=None)
    if held.is_guest:
        return JSONResponse(  # type: ignore[return-value]
            {"signed_in": False, "login": None, "provider": None, "email": None, "kind": "guest"}
        )
    return CatalogSessionResponse.held(held.login, held.provider)


@router.post(
    "/catalog/auth/signout",
    response_model=CatalogSessionResponse,
    dependencies=[Depends(require_auth)],
)
async def catalog_auth_signout(request: Request) -> CatalogSessionResponse:
    """Sign this device out: end its hosted session, then forget the stored sign in.

    The hosted session is revoked first, best effort with the held access
    token, so the device disappears from the account's session list and the
    token dies now rather than at its eight hour end. An unreachable host or
    an already dead session never blocks the local sign out: what this
    machine holds is cleared either way, bytes included.
    """
    await catalog_auth.sign_out(_state_dir(request), _catalog(request).api_base_url())
    return CatalogSessionResponse(signed_in=False, login=None)
