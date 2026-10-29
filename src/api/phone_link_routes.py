
from __future__ import annotations

import asyncio
import base64
import io
from typing import Any, Dict, List, Optional

import qrcode
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from src.api import account_gates
from src.api.auth import _totp_rate_limit, decode_refresh_token, limiter, require_auth
from src.api.auth_routes import redeem_totp_code
from src.core.native_push import wiring as native_wiring
from src.core.phone_link import acme
from src.core.phone_link.custom_domain import names
from src.core.phone_link.custom_domain.control import CustomDomainError
from src.core.phone_link.gate import COOKIE_NAME, PENDING_COOKIE_NAME, read_cookie
from src.core.phone_link.manager import PhoneLinkManager
from src.core.phone_link.pair_page import PAIR_HTML
from src.core.phone_link.pairing import LABEL_MAX, PENDING_SECONDS, QR_ROTATE_SECONDS, ClaimResult, PairingLocked, Throttled
from src.core.web_push.store import public_view
from src.models import VerifyTOTPRequest
from src.core.relay_identity.session import SIGNIN_REQUIRED, RelayAuthError
from src.core.web_push.wiring import sender_for

logger = structlog.get_logger()

COOKIE_MAX_AGE = 365 * 24 * 3600


def _refuse_link(request: Request) -> None:
    if request.scope.get("via_link"):
        raise HTTPException(status_code=403, detail="not available over the link")


def _manager(request: Request) -> PhoneLinkManager:
    manager = getattr(request.app.state, "phone_link", None)
    if manager is None or not manager.available:
        raise HTTPException(status_code=503, detail="mobile sync is unavailable (relay disabled)")
    return manager


router = APIRouter(prefix="/phone-link", tags=["phone-link"],
                   dependencies=[Depends(_refuse_link), Depends(require_auth)])
pair_router = APIRouter(tags=["phone-link"])


class EnableBody(BaseModel):
    """Body of PUT /phone-link."""

    enabled: bool


class PairBody(BaseModel):
    """Body of the claim routes: a secret or a code, and an optional device label."""

    secret: str = Field(default="", max_length=128)
    code: str = Field(default="", max_length=32)
    label: str = Field(default="phone", max_length=LABEL_MAX)


def _qr_png(url: str) -> str:
    qr = qrcode.QRCode(version=None, box_size=8, border=3)
    qr.add_data(url)
    qr.make(fit=True)
    buffer = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


@router.get("")
async def link_status(request: Request) -> Dict[str, Any]:
    """The link's state plus its certificate.

    Output: {available, enabled, running, tunnel, hostname, devices, window_open, pairing, error, cert}, where
    pairing is {state: "none"|"open"|"pending"|"claimed", device: {id, label, kind, created_at} | null} and cert is
    {issuer, not_after, environment} or null before a certificate exists.
    """
    manager = _manager(request)
    return {**manager.status(), "cert": await asyncio.to_thread(manager.cert_info)}


async def _gate_enable(body: EnableBody, request: Request) -> None:
    if body.enabled:
        await account_gates.check(request, "phone_link")


@router.put("", dependencies=[Depends(_gate_enable)])
async def set_link_enabled(body: EnableBody, request: Request) -> Dict[str, Any]:
    """Switch the link on or off (off by default). Output: the new status."""
    manager = _manager(request)
    await manager.set_enabled(body.enabled)
    return {**manager.status(), "cert": await asyncio.to_thread(manager.cert_info)}


def _qr_reply(manager: PhoneLinkManager, secret: str, expires: float) -> Dict[str, Any]:
    host = manager.public_host()
    link = manager.hostname
    query = f"?link={link.split('.', 1)[0]}" if link and host != link else ""
    url = f"https://{host}/pair{query}#{secret}"
    return {"url": url, "qr": _qr_png(url), "qr_expires_at": int(expires)}


@router.post("/pairing-window", dependencies=[Depends(account_gates.require_account("phone_pairing"))])
async def open_pairing_window(request: Request) -> Dict[str, Any]:
    """Open a 10 minute pairing window (replacing any open one).
    """
    manager = _manager(request)
    if not manager.pairing.enabled:
        raise HTTPException(status_code=409, detail="switch mobile sync on first")
    try:
        window = await manager.open_window()
    except PairingLocked:
        return _refusal(409, "pairing_locked")
    if not manager.hostname or manager.error:
        raise HTTPException(status_code=503, detail=manager.error or "mobile sync is not running")
    return {**_qr_reply(manager, window.secret, window.secret_expires_at), "pair_url": f"https://{manager.public_host()}/pair",
            "code": window.code, "expires_at": int(window.expires_at), "qr_rotate_seconds": QR_ROTATE_SECONDS}


@router.post("/pairing-window/qr", dependencies=[Depends(account_gates.require_account("phone_pairing"))])
async def rotate_pairing_qr(request: Request) -> Any:
    """A fresh QR secret for the open window. Output: {url, qr, qr_expires_at}. Raises: 409 ``no_window``, 503."""
    manager = _manager(request)
    rotated = manager.rotate_qr()
    if rotated is None:
        return _refusal(409, "no_window")
    return _qr_reply(manager, *rotated)


@router.post("/pairing-window/acknowledge")
async def acknowledge_pairing_failures(request: Request) -> Dict[str, bool]:
    _manager(request).pairing.acknowledge_failures()
    return {"acknowledged": True}


@router.delete("/pairing-window")
async def close_pairing_window(request: Request) -> Dict[str, bool]:
    """Close the pairing window now (idempotent). Output: {closed: true}."""
    await _manager(request).close_window()
    return {"closed": True}


@router.get("/devices")
async def list_devices(request: Request) -> List[Dict[str, Any]]:
    """Every paired phone. Output: list of {id, label, kind, created_at, last_seen, push}.

    ``push`` is that phone's push subscriptions as {service, last_result} (never an endpoint or a key).
    """
    devices = _manager(request).pairing.devices()
    subs = await asyncio.to_thread(sender_for(request.app.state).store.list)
    return [{**vars(d), "push": [{"service": public_view(r)["service"], "last_result": r.get("last_result")}
                                 for r in subs if r.get("device_id") == d.id]} for d in devices]


@router.delete("/devices/{device_id}")
async def revoke_device(device_id: str, request: Request) -> Dict[str, bool]:
    """Revoke a phone, close its open connections and forget its push subscriptions and native devices. Raises 404 when unknown."""
    revoked = await _manager(request).revoke(device_id)
    await asyncio.to_thread(sender_for(request.app.state).store.remove_for_device, device_id)
    await native_wiring.remove_for_device(request.app.state, device_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="no such device")
    return {"revoked": True}


class CustomDomainBody(BaseModel):
    """Body of PUT /phone-link/custom-domain."""

    domain: str = Field(max_length=300)


def _refusal(status: int, code: str, **extra: Any) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "detail": code.replace("_", " "), **extra})


def _control_refusal(exc: CustomDomainError) -> JSONResponse:
    """Map a control plane refusal to this API's answer: its own status for a 4xx, 502 when it could not be asked."""
    if exc.code == "unreachable" or exc.status >= 500:
        return _refusal(502, "control_unreachable")
    return _refusal(exc.status if exc.status in (400, 403, 404, 409, 429) else 502, exc.code,
                    **({"reason": exc.detail} if exc.code == "bad_domain" else {}))


@router.get("/custom-domain")
async def get_custom_domain(request: Request) -> Dict[str, Any]:
    """The custom name's cached binding. Output: {domain, domain_display, state, target, dead_reason,
    lockout_until, check, cert, error, updated_at}; ``state`` is "none" with no binding."""
    return await asyncio.to_thread(_manager(request).custom.snapshot)


@router.put("/custom-domain", dependencies=[Depends(account_gates.require_account("phone_link"))])
async def put_custom_domain(body: CustomDomainBody, request: Request) -> Any:
    """Bind a custom name (and verify it now). Output: the GET shape.

    Raises: 400 ``bad_domain`` (``reason`` names the rule), 403 ``account_required``, 409 ``domain_exists``,
    429, 502 when the control plane or the CA could not be reached.
    """
    manager = _manager(request)
    try:
        return await manager.custom.submit(body.domain)
    except names.BadDomain as exc:
        return _refusal(400, "bad_domain", reason=exc.reason)
    except CustomDomainError as exc:
        return _control_refusal(exc)
    except acme.AcmeError:
        return _refusal(502, "acme_unreachable")
    except RelayAuthError as exc:
        return _refusal(403, "account_required") if exc.kind == SIGNIN_REQUIRED else _refusal(502, "relay_" + exc.kind)


@router.delete("/custom-domain")
async def delete_custom_domain(request: Request) -> Any:
    """Release the custom name and delete its certificate. Output: the GET shape."""
    try:
        return await _manager(request).custom.remove()
    except CustomDomainError as exc:
        return _control_refusal(exc)
    except RelayAuthError as exc:
        return _refusal(403, "account_required") if exc.kind == SIGNIN_REQUIRED else _refusal(502, "relay_" + exc.kind)


def _require_link(request: Request) -> None:
    if not request.scope.get("via_link"):
        raise HTTPException(status_code=404)


def _real_ip(request: Request) -> str:
    return request.client.host if request.client else "-"


def _host(request: Request) -> str:
    return str(request.scope.get("link_host") or "")


def _issue(response: Response, cookie: str) -> None:
    response.set_cookie(COOKIE_NAME, cookie, max_age=COOKIE_MAX_AGE, path="/",
                        secure=True, httponly=True, samesite="lax")


def _check_claim_request(request: Request) -> None:
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise HTTPException(status_code=415, detail="bad_content_type")
    origin = request.headers.get("origin")
    if origin is not None and origin.strip().lower() != f"https://{_host(request).lower()}":
        raise HTTPException(status_code=403, detail="bad_origin")


def _hold_pending(response: Response, handle: str) -> None:
    response.set_cookie(PENDING_COOKIE_NAME, handle, max_age=int(PENDING_SECONDS), path="/",
                        secure=True, httponly=True, samesite="strict")


async def _answer(manager: PhoneLinkManager, result: Optional[ClaimResult], response: Response, miss: str) -> Dict[str, Any]:
    if result is None:
        raise HTTPException(status_code=403, detail=miss)
    if result.handle is not None:
        _hold_pending(response, result.handle)
        await manager.pending_started()
    return {"ok": True, "status": result.status}


@pair_router.get("/pair", response_class=HTMLResponse, dependencies=[Depends(_require_link)])
async def pair_page() -> HTMLResponse:
    """The pair page shell (its bundle and stylesheet are public assets, see the gate)."""
    return HTMLResponse(PAIR_HTML, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@pair_router.get("/pair/status", dependencies=[Depends(_require_link)])
async def pair_status(request: Request) -> JSONResponse:
    """Where this browser stands. Output: {paired, pending}: a pairing cookie valid for this name, and a scanned
    pairing of this browser still waiting for its authenticator code."""
    manager = _manager(request)
    cookie = read_cookie(request.scope)
    paired = bool(cookie and manager.pairing.device_for_cookie(cookie, _host(request), manager.hostname))
    pending = manager.pairing.has_pending(read_cookie(request.scope, PENDING_COOKIE_NAME))
    return JSONResponse({"paired": paired, "pending": pending}, headers={"Cache-Control": "no-store"})


@pair_router.post("/pair/claim", dependencies=[Depends(_require_link), Depends(_check_claim_request)])
async def claim(body: PairBody, request: Request, response: Response) -> Dict[str, Any]:
    """Redeem the QR secret into a PENDING pairing bound to this browser (no device yet: the authenticator code
    completes it at ``/pair/verify``). A browser that is already paired is told so and nothing is consumed.

    Output: {ok, status: "pending" | "already_paired"}.
    Raises: 403 ``link_used`` for a wrong, dead or spent secret, 429 when this address missed too often.
    """
    manager = _manager(request)
    try:
        result = manager.pairing.claim_secret(body.secret, _real_ip(request), body.label, _host(request),
                                              read_cookie(request.scope), manager.hostname)
    except Throttled:
        raise HTTPException(status_code=429, detail="too many tries") from None
    return await _answer(manager, result, response, "link_used")


@pair_router.post("/pair/code", dependencies=[Depends(_require_link), Depends(_check_claim_request)])
async def claim_code(body: PairBody, request: Request, response: Response) -> Dict[str, Any]:
    """Redeem the window's typed code into a pending pairing, exactly like ``/pair/claim``.

    Output: {ok, status: "pending" | "already_paired"}. Raises: 403 ``wrong_code``, 429 when this address missed too often.
    """
    manager = _manager(request)
    try:
        result = manager.pairing.claim_code(body.code, _real_ip(request), body.label, _host(request),
                                            read_cookie(request.scope), manager.hostname)
    except Throttled:
        raise HTTPException(status_code=429, detail="too many tries") from None
    return await _answer(manager, result, response, "wrong_code")


async def _revoke_orphan(request: Request, refresh_token: str) -> None:
    store = getattr(request.app.state, "refresh_store", None)
    if store is None:
        return
    try:
        await store.revoke(decode_refresh_token(refresh_token)["jti"])
    except (HTTPException, KeyError) as exc:
        logger.error("phone_link_orphan_token_revoke_failed", error=repr(exc))


@pair_router.post("/pair/verify", dependencies=[Depends(_require_link), Depends(_check_claim_request)])
@limiter.limit(_totp_rate_limit)
async def verify_pairing(request: Request, response: Response, body: VerifyTOTPRequest) -> Dict[str, Any]:
    """Complete a pending pairing with the authenticator code, in one step.

    Description: the code goes through the ordinary TOTP check (``redeem_totp_code``: replay cache, ``pyotp``,
      token mint), then the device row and its cookie are created and the signed-in token pair is answered for
      the page to keep where the app keeps it. At most 5 tries per pending pairing, then it dies; the TOTP rate
      limit applies on top.
    Output: {ok, status: "paired", access_token, refresh_token}.
    Raises: 403 ``no_pending`` (no live pending for this browser) or ``pairing_dead`` (its tries ran out); 401 a wrong
      or reused code; 429.
    """
    manager = _manager(request)
    handle = read_cookie(request.scope, PENDING_COOKIE_NAME)
    if manager.pairing.begin_attempt(handle) is None:
        raise HTTPException(status_code=403, detail="no_pending")
    try:
        tokens = await redeem_totp_code(request, body.code)
    except HTTPException as exc:
        if exc.status_code == 401 and manager.pairing.drop_if_spent(handle):
            await manager.reconcile()
            raise HTTPException(status_code=403, detail="pairing_dead") from None
        raise
    cookie = manager.pairing.complete_pending(handle, _host(request))
    if cookie is None:
        await _revoke_orphan(request, tokens.refresh_token)
        raise HTTPException(status_code=403, detail="no_pending")
    _issue(response, cookie)
    response.delete_cookie(PENDING_COOKIE_NAME, path="/", secure=True, httponly=True, samesite="strict")
    response.headers["Cache-Control"] = "no-store"
    await manager.reconcile()
    return {"ok": True, "status": "paired", "access_token": tokens.access_token, "refresh_token": tokens.refresh_token}
