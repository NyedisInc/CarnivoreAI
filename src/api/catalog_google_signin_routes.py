
from __future__ import annotations

from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.auth import require_auth
from src.api.catalog_email_signin_routes import (
    _flows as _proof_flows,
    _proof_of_work,
    verify_flow,
)
from src.core.catalog.email_flow import MAILBOX_PATHS
from src.api.catalog_hosted_routes import (
    _flows as _device_flows,
    _hosted,
    _relay,
    _required_string,
    _seconds,
    finish_device_flow,
    open_device_flow,
)
from src.models.catalog_signin import (
    CatalogSessionResponse,
    DevicePollRequest,
    DeviceStartResponse,
    EmailStartResponse,
    EmailVerifyRequest,
    GoogleProofResponse,
)

router = APIRouter(tags=["catalog"])


@router.post(
    "/catalog/auth/google/start",
    response_model=DeviceStartResponse,
    dependencies=[Depends(require_auth)],
)
async def catalog_google_start(request: Request) -> DeviceStartResponse:
    """Open a Google device flow and hand back what a person must read.

    Raises:
        HTTPException(502): the hosted api could not be reached, or opened a
            flow with no code in it.
        HTTPException(503): ``auth_not_configured``, relayed.
    """
    proof = await _proof_of_work(request)
    return await open_device_flow(request, "/auth/google/start", {"pow": proof} if proof else {})


@router.post(
    "/catalog/auth/google/poll",
    response_model=Union[CatalogSessionResponse, GoogleProofResponse],
    dependencies=[Depends(require_auth)],
)
async def catalog_google_poll(
    request: Request, body: DevicePollRequest
) -> Union[CatalogSessionResponse, GoogleProofResponse]:
    """Ask whether the person has finished at google.com, and store the session if so.

    A 428 is not a failure (keep polling); see ``finish_device_flow``. A hosted
    403 ``mailbox_proof_required`` is not one either: the code is requested and
    ``GoogleProofResponse`` answered (see ``_mailbox_proof``).

    Raises:
        HTTPException(400): ``unknown_flow``.
        HTTPException(428): relayed, keep waiting.
        HTTPException(502): the hosted api could not be reached.
    """
    try:
        return await finish_device_flow(request, body, "/auth/google/poll", provider="google")
    except HTTPException as refusal:
        detail = refusal.detail if isinstance(refusal.detail, dict) else {}
        if refusal.status_code != 403 or detail.get("code") != "mailbox_proof_required":
            raise
        return await _mailbox_proof(request, body.flow_id, _required_string(detail, "ticket"))


async def _mailbox_proof(
    request: Request, flow_id: str, ticket: str, provider: str = "google"
) -> GoogleProofResponse:
    hosted_body = _relay(await _hosted(
        request, "POST", MAILBOX_PATHS[provider][0], json_body={"ticket": ticket}
    ))
    expires_in = _seconds(hosted_body, "expires_in", 900)
    destination = _required_string(hosted_body, "destination")
    _device_flows.finish(flow_id)
    return GoogleProofResponse(mailbox_proof=EmailStartResponse(
        flow_id=_proof_flows.start(
            email=destination, session=_required_string(hosted_body, "session"),
            expires_in=expires_in, ticket=ticket, provider=provider,
        ),
        destination=destination,
        expires_in=expires_in,
    ))


@router.post(
    "/catalog/auth/google/mailbox/verify",
    response_model=CatalogSessionResponse,
    dependencies=[Depends(require_auth)],
)
async def catalog_google_mailbox_verify(
    request: Request, body: EmailVerifyRequest
) -> CatalogSessionResponse:
    """Answer the mailbox proof with the emailed code and store the Google session.

    The rules are the email verify's (``verify_flow``): a typo keeps the flow, a
    410 ends it, the tokens are stored here and never returned.

    Raises:
        HTTPException(400): ``unknown_flow``, ``bad_code`` or a relayed mismatch.
        HTTPException(403), (410), (429), (502): relayed.
    """
    return await verify_flow(request, body, "/auth/google/mailbox/verify", ticket_flow=True)
