
import asyncio
import base64
import io
import os
from pathlib import Path
from typing import Any, Optional

import structlog
from dotenv import dotenv_values
from fastapi import APIRouter, HTTPException, Request, Response
from qrcode import ERROR_CORRECT_M, make as make_qr
from qrcode.exceptions import DataOverflowError
from qrcode.image.svg import SvgPathFillImage

from src.api import enrollment_gate as gate
from src.api.auth import limiter
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
    except OSError:
        return False
    for key, value in values.items():
        if key.lower() == "totp_secret" and value and value.strip():
            return value.strip() != memory_secret.strip()
    return False


def _render_qr(uri: str) -> str:
    image = make_qr(uri, image_factory=SvgPathFillImage, border=4, error_correction=ERROR_CORRECT_M)
    buffer = io.BytesIO()
    image.save(buffer)
    return "data:image/svg+xml;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


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
