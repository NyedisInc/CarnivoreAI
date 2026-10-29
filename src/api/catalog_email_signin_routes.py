
from __future__ import annotations

from typing import Any, Dict

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.auth import require_auth
from src.api.catalog_client_status import client_status
from src.api.catalog_hosted_routes import (
    install_id as _install_id,
    _hosted,
    _relay,
    _required_string,
    _seconds,
    _state_dir,
)
from src.core.catalog import pow_client
from src.core.catalog.device_label import device_fields
from src.core.catalog.email_flow import MAILBOX_PATHS, EmailFlowStore
from src.core.catalog import catalog_auth
from src.core.catalog.token_store import CatalogSession
from src.models.catalog_signin import (
    CatalogSessionResponse,
    EmailStartRequest,
    EmailStartResponse,
    EmailVerifyRequest,
)

logger = structlog.get_logger()

router = APIRouter(tags=["catalog"])

_flows = EmailFlowStore()

MAX_EMAIL_CHARS = 254

MAX_CODE_CHARS = 16

_FLOW_IS_OVER = 410


def _clean_email(raw: str) -> str:
    address = raw.strip().lower()
    local, separator, domain = address.partition("@")
    if (
        not separator
        or not local
        or not domain
        or "@" in domain
        or len(address) > MAX_EMAIL_CHARS
        or any(character.isspace() for character in address)
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "bad_email",
                "detail": "that is not an email address this can send a code to",
            },
        )
    return address


def _clean_code(raw: str) -> str:
    code = raw.strip()
    if not code or len(code) > MAX_CODE_CHARS or not code.isdigit():
        raise HTTPException(
            status_code=400,
            detail={"code": "bad_code", "detail": "that is not a code from an email"},
        )
    return code


def _unknown_flow() -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={
            "code": "unknown_flow",
            "detail": "that sign in is not in progress on this server",
        },
    )


async def _proof_of_work(request: Request) -> str:
    answer = await _hosted(request, "POST", "/pow", json_body={})
    if answer.status == 404:
        return ""
    try:
        return await pow_client.solve_off_loop(_relay(answer))
    except pow_client.PowUnsolvable as exc:
        logger.warning("catalog_pow_unsolvable", reason=str(exc))
        raise HTTPException(
            status_code=502,
            detail={"code": "unavailable", "detail": "the sign in service could not be reached"},
        ) from exc


@router.post(
    "/catalog/auth/email/start",
    response_model=EmailStartResponse,
    dependencies=[Depends(require_auth)],
)
async def catalog_email_start(
    request: Request, body: EmailStartRequest
) -> EmailStartResponse:
    """Ask the catalog to email a code, and remember the challenge here.

    **THE COGNITO SESSION STAYS ON THIS SERVER.** The hosted api answers
    a session string and a masked destination. Only the second is
    returned; the first is held in memory against a random flow id, so a
    page somebody else reads carries nothing they could finish this sign
    in with.

    **THE MASK COMES FROM UPSTREAM AND IS NOT RECOMPUTED HERE.** The
    hosted route masks the address it was given, and a second masking
    rule on this side would be a second thing to get wrong about
    somebody's address.

    Raises:
        HTTPException(400): ``bad_email`` - refused before any upstream
            call, so a malformed address never spends a send.
        HTTPException(429): relayed ``rate_limited``, carrying the wait.
        HTTPException(502): the hosted api could not be reached, or
            opened a challenge with no session or no destination in it.
        HTTPException(503): ``email_auth_not_configured``, the live state
            until the cognito pool is wired. Relayed with its own code,
            distinct from the GitHub 503, so only the email control
            disables.
    """
    email = _clean_email(body.email)
    relayed: Dict[str, Any] = {"email": email}
    proof = await _proof_of_work(request)
    if proof:
        relayed["pow"] = proof
    answer = await _hosted(request, "POST", "/auth/email/start", json_body=relayed)
    hosted_body = _relay(answer)
    expires_in = _seconds(hosted_body, "expires_in", 900)
    flow_id = _flows.start(
        email=email,
        session=_required_string(hosted_body, "session"),
        expires_in=expires_in,
    )
    return EmailStartResponse(
        flow_id=flow_id,
        destination=_required_string(hosted_body, "destination"),
        expires_in=expires_in,
    )


def _store_session(
    request: Request, hosted_body: Dict[str, Any], provider: str = "email"
) -> CatalogSession:
    _required_string(hosted_body, "login")
    _required_string(hosted_body, "access_token")
    _required_string(hosted_body, "refresh_token")
    return catalog_auth.save_session(_state_dir(request), hosted_body, provider)


@router.post(
    "/catalog/auth/email/verify",
    response_model=CatalogSessionResponse,
    dependencies=[Depends(require_auth)],
)
async def catalog_email_verify(
    request: Request, body: EmailVerifyRequest
) -> CatalogSessionResponse:
    """Answer the challenge with the typed code, and store what it mints.

    **THE ADDRESS AND THE SESSION COME FROM MEMORY, NOT FROM THE BODY.**
    See this module's header: a body carrying the address would let a
    caller aim a challenge at a different username.

    **WHAT COMES BACK IS A NAME, NEVER A TOKEN.** The minted pair is
    written to the 0600 store described in
    ``src/core/catalog/token_store.py`` and never leaves this server.

    Raises:
        HTTPException(400): ``unknown_flow`` when no such flow is in
            progress here, refused before any upstream call;
            ``bad_code`` for a body that is not a code; relayed
            ``code_mismatch`` for a wrong one.
        HTTPException(403): relayed ``account_disabled``.
        HTTPException(410): relayed ``code_expired``. The flow is
            forgotten here too, so a retry says ``unknown_flow`` rather
            than spending another upstream call on a dead challenge.
        HTTPException(429): relayed ``rate_limited``.
        HTTPException(502): the hosted api could not be reached, or
            finished a sign in with no token in it.
    """
    return await verify_flow(request, body, "/auth/email/verify", ticket_flow=False)


def _consent_fields(body: EmailVerifyRequest) -> Dict[str, Any]:
    return {key: value for key, value in (("consent", body.consent), ("src", body.src)) if value is not None}


async def verify_flow(
    request: Request, body: EmailVerifyRequest, path: str, *, ticket_flow: bool
) -> CatalogSessionResponse:
    pending = _flows.pending_for(body.flow_id)
    if pending is None or bool(pending.ticket) != ticket_flow:
        raise _unknown_flow()
    if ticket_flow:
        path = MAILBOX_PATHS[pending.provider][1]
    code = _clean_code(body.code)
    answer = await _hosted(
        request,
        "POST",
        path,
        json_body={
            ("ticket" if ticket_flow else "email"): pending.ticket or pending.email,
            "session": pending.session,
            "code": code,
            "install_id": _install_id(request),
            **device_fields(),
            **_consent_fields(body),
        },
    )
    if answer.status >= 400:
        if answer.status == _FLOW_IS_OVER:
            _flows.finish(body.flow_id)
        raise HTTPException(
            status_code=client_status(answer.status), detail=dict(answer.body)
        )

    session = _store_session(request, answer.body, pending.provider if ticket_flow else "email")
    _flows.finish(body.flow_id)
    return CatalogSessionResponse.held(session.login, session.provider)
