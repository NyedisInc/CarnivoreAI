
from __future__ import annotations

from typing import Union

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.auth import require_auth
from src.api.catalog_email_signin_routes import _proof_of_work
from src.api.catalog_google_signin_routes import _mailbox_proof
from src.api.catalog_hosted_routes import (
    _catalog,
    install_id as _install_id,
    _hosted,
    _relay,
    _required_string,
    _seconds,
    _state_dir,
)
from src.core.catalog import catalog_auth
from src.core.catalog.device_label import device_fields
from src.core.catalog.web_signin_flows import WebFlowStore, challenge_of, new_verifier
from src.models.catalog_signin import (
    CatalogSessionResponse,
    DevicePollRequest,
    GoogleProofResponse,
    WebPollPending,
    WebStartRequest,
    WebStartResponse,
)

logger = structlog.get_logger()

router = APIRouter(tags=["catalog"])

_flows = WebFlowStore()

_KEEP_FLOW = frozenset({428, 429, 502, 503})


@router.post(
    "/catalog/auth/web/start",
    response_model=WebStartResponse,
    dependencies=[Depends(require_auth)],
)
async def catalog_web_start(request: Request, body: WebStartRequest) -> WebStartResponse:
    """Open a browser sign in: keep a fresh verifier here and answer the link to open.

    Raises:
        HTTPException(502): the hosted api could not be reached, or answered no flow.
        HTTPException(400, 409, 429, 503): relayed (``bad_consent``, ``terms_stale``,
            ``rate_limited``, ``auth_not_configured``).
    """
    verifier = new_verifier()
    hosted_body = {
        "provider": body.provider,
        "src": body.src,
        "challenge": challenge_of(verifier),
        "consent": body.consent.model_dump(),
        **device_fields(),
    }
    proof = await _proof_of_work(request)
    if proof:
        hosted_body["pow"] = proof
    answer = _relay(await _hosted(request, "POST", "/auth/web/start", json_body=hosted_body))
    flow_id = _required_string(answer, "flow_id")
    expires_in = _seconds(answer, "expires_in", 600)
    _flows.start(flow_id, verifier, body.provider, expires_in)
    return WebStartResponse(
        flow_id=flow_id,
        url=_required_string(answer, "url"),
        expires_in=expires_in,
        interval=_seconds(answer, "interval", 3),
    )


@router.post(
    "/catalog/auth/web/poll",
    response_model=Union[CatalogSessionResponse, GoogleProofResponse, WebPollPending],
    dependencies=[Depends(require_auth)],
)
async def catalog_web_poll(
    request: Request, body: DevicePollRequest
) -> Union[CatalogSessionResponse, GoogleProofResponse, WebPollPending]:
    """Ask whether the person has finished in the browser; store the session if so.

    A hosted 428 is not a failure: it answers ``{"status": "pending", "interval"}``. A 403
    ``mailbox_proof_required`` answers ``GoogleProofResponse``. Any other refusal that ends
    the flow (410, 400, 403) is relayed with its hosted code and the verifier is forgotten.

    Raises:
        HTTPException(400): ``unknown_flow`` (refused before anything is sent upstream), or
            a relayed hosted 400.
        HTTPException(403, 410): relayed, the flow is over.
        HTTPException(429, 502, 503): relayed, the flow is kept for another poll.
    """
    flow = _flows.get(body.flow_id)
    if flow is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "unknown_flow", "detail": "that sign in is not in progress on this server"},
        )
    answer = await _hosted(
        request, "POST", "/auth/web/poll",
        json_body={
            "flow_id": body.flow_id, "verifier": flow.verifier,
            "install_id": _install_id(request), **device_fields(),
        },
    )
    if answer.status == 428:
        return WebPollPending(interval=_seconds(answer.body, "interval", 3))
    if answer.status >= 400:
        detail = answer.body if isinstance(answer.body, dict) else {}
        if answer.status == 403 and detail.get("code") == "mailbox_proof_required":
            proof = await _mailbox_proof(request, body.flow_id, _required_string(detail, "ticket"), flow.provider)
            _flows.finish(body.flow_id)
            return proof
        if answer.status not in _KEEP_FLOW:
            _flows.finish(body.flow_id)
        _relay(answer)
    for field in ("login", "access_token", "refresh_token"):
        _required_string(answer.body, field)
    session = catalog_auth.save_session(_state_dir(request), answer.body, flow.provider)
    _flows.finish(body.flow_id)
    return CatalogSessionResponse.held(session.login, session.provider)
