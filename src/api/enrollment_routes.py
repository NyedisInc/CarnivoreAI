
import asyncio
import base64
import hmac
import io
import time
import os
from pathlib import Path
from typing import Any, Optional

import pyotp
import structlog
from dotenv import dotenv_values
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from qrcode import ERROR_CORRECT_M, make as make_qr
from qrcode.exceptions import DataOverflowError
from qrcode.image.svg import SvgPathFillImage

from src.api import enrollment_gate as gate
from src.api.auth import _totp_seen_cache, _totp_seen_lock, limiter, require_auth
from src.config import settings
from src.core import setup_state
from src.core.computers import membership
from src.core.hosts.machine_identity import computer_display_name
from src.core.owner_identity.otpauth import ISSUER, build_otpauth_uri, sanitize_account

logger = structlog.get_logger()

router = APIRouter()

_NO_STORE = {"Cache-Control": "no-store"}


def env_file_path() -> Path:
    return Path(settings.model_config["env_file"]).expanduser().resolve()


def _refuse(status: int, reason: str, **extra: Any) -> HTTPException:
    logger.info("enrollment_refused", reason=reason, **extra)
    return HTTPException(status_code=status, detail={"reason": reason}, headers=_NO_STORE)


def _disk_secret_differs(memory_secret: str) -> bool:
    if any(k.lower() == "totp_secret" for k in os.environ):
        return False
    try:
        values = dotenv_values(env_file_path())
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("enrollment_env_unreadable", error_type=type(exc).__name__)
        return False
    for key, value in values.items():
        if key.lower() == "totp_secret" and value and value.strip():
            return not hmac.compare_digest(value.strip().encode(), memory_secret.strip().encode())
    return False


def _render_qr(uri: str) -> str:
    image = make_qr(uri, image_factory=SvgPathFillImage, border=4, error_correction=ERROR_CORRECT_M)
    buffer = io.BytesIO()
    image.save(buffer)
    return "data:image/svg+xml;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _loaded_secret_for_local_program(request: Request) -> str:
    if not gate.is_local_non_browser(request):
        raise _refuse(403, "enrollment_local_only")
    try:
        return settings.load_auth_config().totp_secret
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise _refuse(503, "config_unreadable", error_type=type(exc).__name__)


_TOTP_STEP_SECONDS = 30


async def _unspent_code(secret: str) -> Optional[str]:
    totp = pyotp.TOTP(secret)
    async with _totp_seen_lock:
        for offset in (0, _TOTP_STEP_SECONDS):
            code = totp.at(time.time() + offset)
            if code not in _totp_seen_cache:
                return code
    return None


@router.get("/auth/enrollment/status")
@limiter.limit("30/minute")
async def enrollment_status(request: Request, response: Response) -> dict[str, Any]:
    """Public probe: paired state and whether this request could fetch the secret.

    Inputs: request; response (slowapi header injection). Output:
    ``{"paired": bool | None, "local": bool, "joined": bool | None, "join_pending": bool}``, no-store.
    """
    response.headers["Cache-Control"] = "no-store"
    return {
        "paired": gate.paired_state(),
        "local": gate.is_local_transport(request),
        "joined": setup_state.current_setup_state().joined,
        "join_pending": membership.first_run_state() == "join_pending",
    }


@router.get("/auth/enrollment")
@limiter.limit("10/minute")
async def get_enrollment(request: Request, response: Response) -> dict[str, Any]:
    """Hand out the authenticator secret, URI and QR to a local first-run browser.

    Refusal order is design-v2 B1 plus F1: not local 403, joined 409, undetermined 503, already
    paired 409, no secret 503, config unreadable 503, restart pending 409, QR
    failure 500. Inputs: request; response. Output: otpauth_uri, secret,
    qr_image, issuer, account.
    """
    paired = gate.paired_state()
    if not gate.is_local_transport(request):
        raise _refuse(403, "enrollment_local_only")
    if setup_state.current_setup_state().joined:
        raise _refuse(409, "joined")
    if paired is None:
        raise _refuse(503, "setup_undetermined")
    if paired and not gate.repair_hatch_open():
        raise _refuse(409, "already_paired")
    if not (settings.totp_secret or "").strip():
        raise _refuse(503, "totp_not_configured")
    try:
        secret = settings.load_auth_config().totp_secret
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise _refuse(503, "config_unreadable", error_type=type(exc).__name__)
    if await asyncio.to_thread(_disk_secret_differs, secret):
        raise _refuse(409, "restart_pending")
    name = await asyncio.to_thread(computer_display_name)
    try:
        uri = build_otpauth_uri(secret, name)
        qr_image = _render_qr(uri)
    except (DataOverflowError, ValueError) as exc:
        raise _refuse(500, "qr_generation_failed", error_type=type(exc).__name__)

    bound: Optional[str] = setup_state.recorded_bound_host()
    if bound is None or not gate.is_loopback_host(bound):
        logger.warning("enrollment_served_unlocked_bind", bound_host=bound or "unrecorded")
    if paired:
        logger.warning("enrollment_repair_hatch_served")
    logger.info("enrollment_served")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return {
        "otpauth_uri": uri,
        "secret": secret,
        "qr_image": qr_image,
        "issuer": ISSUER,
        "account": sanitize_account(name),
    }


@router.get("/auth/enrollment/loaded", dependencies=[Depends(require_auth)])
@limiter.limit("10/minute")
async def get_loaded_enrollment(request: Request, response: Response) -> dict[str, Any]:
    """The otpauth URI of the secret THIS running server verifies codes against (tray QR, #2707).

    The tray used to read ``.env`` itself, which after a rotation that was never loaded shows a secret
    this server rejects. Unlike ``/auth/enrollment`` this serves a paired install: the caller already
    holds a login token (an API key is fenced out by ``/api/v1/auth/``) AND must be a local program:
    loopback, main listener, no link tag, no forwarding header, and no ``Origin`` or ``Sec-Fetch-Site``
    (so no browser page). ``restart_pending`` says the env file now holds a different secret than the
    one served. Inputs: request; response. Output: ``{"otpauth_uri": str, "restart_pending": bool}``,
    no-store. Refusals: 403 ``enrollment_local_only``, 503 ``config_unreadable``,
    500 ``qr_generation_failed``. No log line carries the secret or URI.
    """
    secret = _loaded_secret_for_local_program(request)
    name = await asyncio.to_thread(computer_display_name)
    try:
        uri = build_otpauth_uri(secret, name)
    except ValueError as exc:
        raise _refuse(500, "qr_generation_failed", error_type=type(exc).__name__)
    pending = await asyncio.to_thread(_disk_secret_differs, secret)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    logger.info("enrollment_loaded_served", restart_pending=pending)
    return {"otpauth_uri": uri, "restart_pending": pending}


@router.get("/auth/enrollment/loaded/code", dependencies=[Depends(require_auth)])
@limiter.limit("10/minute")
async def get_loaded_code(request: Request, response: Response) -> dict[str, Any]:
    """The current one-time code of the secret THIS running server verifies against (tray Copy OTP, #2712).

    The tray used to compute the code from ``.env``, which after an unloaded rotation is a code this server
    rejects. The server computes it instead, so the secret never leaves the process. Same fences as
    ``/auth/enrollment/loaded`` (login token, local non-browser caller). While ``.env`` holds a different
    secret (``restart_pending``) no code is served: it would stop working at the restart. Inputs: request;
    response. Output: ``{"code": str | None, "restart_pending": bool}``, no-store. Refusals as the URI route.
    The code is not consumed here; a code the replay cache already holds is skipped for the next step's. No log line carries it.
    """
    secret = _loaded_secret_for_local_program(request)
    pending = await asyncio.to_thread(_disk_secret_differs, secret)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    logger.info("enrollment_loaded_code_served", restart_pending=pending)
    return {"code": None if pending else await _unspent_code(secret), "restart_pending": pending}


@router.get("/auth/qr")
async def qr_moved() -> None:
    """Tombstone for the old QR route: always 403 ``qr_moved``, serves nothing.

    A stale login tab treats 403 as "paired, show the form"; a 404 would put a
    false setup banner on it. Never reads the secret, sentinel or hatch.
    """
    raise HTTPException(
        status_code=403,
        detail={
            "reason": "qr_moved",
            "message": "this page is out of date. reload it, then pair on the carnivore setup screen on this computer.",
        },
        headers=_NO_STORE,
    )
