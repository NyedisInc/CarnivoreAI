
import pyotp
import structlog
import time
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from src.config import settings
from src.core.owner_identity.identity import os_account_full_name
from src.models import AuthTokenResponse, SuccessResponse, VerifyTOTPRequest

from src.api import config_routes
from src.api import enrollment_routes
from src.api import join_local_routes
from src.api import project_clone_routes
from src.api import projects_routes
from src.api import workspace_settings_routes
from src.core.refresh_rotation.replay import RotatedPair
from src.core.setup_state import PACK_LEFT_NAME
from src.api.auth import _get_ttls, _totp_paired_sentinel_path, _totp_rate_limit, _totp_seen_cache, _totp_seen_lock, create_access_token, create_refresh_token, decode_refresh_token, limiter, require_auth

logger = structlog.get_logger()
pairing_router = APIRouter()

status_router = APIRouter()

router = APIRouter()


async def check_totp_code(code: str) -> None:
    auth_config = settings.load_auth_config()
    totp = pyotp.TOTP(auth_config.totp_secret)
    async with _totp_seen_lock:
        if code in _totp_seen_cache:
            logger.warning("totp_code_reused")
            raise HTTPException(status_code=401, detail={"success": False, "reason": "code_reused"})
        if not totp.verify(code, valid_window=1):
            logger.warning("totp_verification_failed")
            raise HTTPException(status_code=401, detail="Invalid authentication code")
        _totp_seen_cache[code] = time.monotonic()


async def redeem_totp_code(request: Request, code: str) -> AuthTokenResponse:
    try:
        await check_totp_code(code)

        access_token, expires_in = create_access_token()
        refresh_token, refresh_jti, refresh_exp = create_refresh_token()

        store = getattr(request.app.state, "refresh_store", None)
        if store is not None:
            try:
                await store.issue(refresh_jti, "claudetunnel_user", refresh_exp)
            except Exception as e:
                logger.error("refresh_store_issue_failed", error=str(e))
                raise HTTPException(
                    status_code=500,
                    detail="Failed to persist refresh token",
                )

        logger.info("totp_verification_success")

        try:
            sentinel = _totp_paired_sentinel_path()
            sentinel.parent.mkdir(parents=True, exist_ok=True)
            sentinel.touch(exist_ok=True)
            sentinel.with_name(PACK_LEFT_NAME).unlink(missing_ok=True)
        except Exception as e:
            logger.error("totp_paired_sentinel_write_failed", error=str(e))

        return AuthTokenResponse(
            success=True,
            access_token=access_token,
            refresh_token=refresh_token,
            token=access_token,
            expires_in=expires_in,
        )

    except FileNotFoundError as e:
        logger.error("auth_config_missing", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Authentication not configured. Run setup_auth.py first."
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("totp_verification_error", error=str(e))
        raise HTTPException(status_code=500, detail="authentication error")


@pairing_router.post("/auth/verify", response_model=AuthTokenResponse)
@limiter.limit(_totp_rate_limit)
async def verify_totp(request: Request, response: Response, body: VerifyTOTPRequest):
    """
    Verify TOTP code and return JWT token.

    Defense layers, outermost first:
      1. slowapi rate limit (5/min;20/hour by default) - caps brute-force
         attempts per client IP. Returns 429 with Retry-After.
      2. Replay dedup (TTLCache keyed on code, 90s TTL) - a single captured
         valid code cannot be replayed within pyotp's ±1-step window.
         Returns 401 with ``reason: code_reused``.
      3. ``pyotp.TOTP.verify`` with valid_window=1 - the actual OTP check.

    Args:
        request: Required by slowapi to extract the rate-limit key.
        response: Required by slowapi to inject X-RateLimit-* and Retry-After
            headers when ``headers_enabled=True`` on the Limiter.
        body: Request with TOTP code.

    Returns:
        JWT token and expiry time.

    Raises:
        HTTPException: If verification fails (401) or config missing (500).
    """
    return await redeem_totp_code(request, body.code)


class RefreshTokenRequest(BaseModel):
    """Body for /auth/refresh and /auth/logout."""
    refresh_token: str = Field(..., description="Opaque refresh JWT issued by /auth/verify")


@pairing_router.post("/auth/refresh", response_model=AuthTokenResponse)
@limiter.limit("10/minute")
async def refresh_tokens(request: Request, response: Response, body: RefreshTokenRequest):
    """
    Rotate a refresh token into a new access+refresh pair.

    Security properties:
      * JWT is decoded with ``algorithms=["HS256"]`` and ``typ == "refresh"``
        enforced - no access-token smuggling into this endpoint.
      * The jti must be present in the RefreshStore AND pass ``is_valid``
        (not revoked, not expired, either not superseded OR within the
        grace window).
      * If we detect the jti has already been superseded past the grace
        window, we treat this as a stolen-token event: walk the chain
        via ``superseded_by`` forward from this jti and revoke every
        descendant. Both parties (legitimate user + attacker) must
        re-authenticate via TOTP.
      * Rotation itself is atomic inside ``RefreshStore.rotate``.
      * Rate-limited at 10/minute to cap abusive retry storms - legitimate
        clients refresh roughly once per ~14min (15min access TTL minus a
        safety margin), so 10/min is ample headroom while throttling
        brute-force campaigns hard.
    """
    store = getattr(request.app.state, "refresh_store", None)
    if store is None:
        logger.error("refresh_store_not_available")
        raise HTTPException(
            status_code=503,
            detail="Refresh service not available",
        )

    claims = decode_refresh_token(body.refresh_token)
    old_jti = claims.get("jti")
    user = claims.get("sub", "claudetunnel_user")
    if not old_jti:
        raise HTTPException(status_code=401, detail="Malformed refresh token")

    _, _, grace = _get_ttls()

    if not await store.is_valid(old_jti, grace_seconds=grace):
        if await store.is_superseded(old_jti):
            logger.warning("refresh_reuse_detected", jti=old_jti[:8] + "…")
            await store.revoke_chain(old_jti)
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    new_access, expires_in = create_access_token(user=user)
    new_refresh, new_jti, new_exp = create_refresh_token(user=user)

    ok = await store.rotate(old_jti, new_jti, user, new_exp)
    if not ok:
        replay = await _replay_lost_race(store, old_jti)
        if replay is not None:
            return replay
        logger.warning(
            "refresh_rotate_lost_race_in_grace", jti=old_jti[:8] + "…"
        )
        raise HTTPException(
            status_code=401,
            detail="Refresh token already rotated; retry with latest token",
        )

    store.recent_rotations.remember(
        old_jti,
        RotatedPair(
            access_token=new_access,
            refresh_token=new_refresh,
            refresh_jti=new_jti,
            access_expires_at=time.time() + expires_in,
        ),
        ttl_seconds=grace,
    )
    return AuthTokenResponse(
        success=True,
        access_token=new_access,
        refresh_token=new_refresh,
        token=new_access,
        expires_in=expires_in,
    )


async def _replay_lost_race(store, old_jti: str) -> Optional[AuthTokenResponse]:
    pair = store.recent_rotations.recall(old_jti)
    if pair is None or not await store.is_valid(pair.refresh_jti, grace_seconds=0):
        return None
    logger.info("refresh_rotate_replayed_in_grace", jti=old_jti[:8] + "…")
    return AuthTokenResponse(
        success=True,
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        token=pair.access_token,
        expires_in=max(0, int(pair.access_expires_at - time.time())),
    )


@pairing_router.post("/auth/logout", response_model=SuccessResponse)
async def logout(request: Request, body: RefreshTokenRequest):
    """
    Revoke a refresh token.

    The access token is left alone - it expires on its own TTL (default
    15m) so a true logout requires either waiting out that window or
    telling the client to drop its access token too (which we do from
    the browser side by clearing localStorage).

    Returns 200 regardless of whether the refresh token was known, to
    avoid an enumeration oracle. We still log the distinction internally.
    """
    store = getattr(request.app.state, "refresh_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Refresh service not available")

    try:
        claims = decode_refresh_token(body.refresh_token)
        jti = claims.get("jti")
        if jti:
            await store.revoke(jti)
    except HTTPException:
        logger.info("logout_with_invalid_refresh")
    except Exception as e:
        logger.error("logout_error", error=str(e))

    return SuccessResponse(success=True, message="Logged out")


class AuthStatusResponse(SuccessResponse):

    owner_os_name: Optional[str] = Field(
        default=None,
        description="The macOS account's full name (first part of pw_gecos), or null when it has none. "
        "Never the login name.",
    )


@status_router.get("/auth/status", response_model=AuthStatusResponse, dependencies=[Depends(require_auth)])
async def check_auth_status() -> AuthStatusResponse:
    """
    Check if user is authenticated (used by frontend to verify token), and name the owner.

    Returns:
        Success response if authenticated; ``owner_os_name`` is the operating-system account's
        full name for the drawer's account chip (the explicit ``ui_preferences.owner_display_name``
        outranks it client side), or null.

    Raises:
        HTTPException: If not authenticated
    """
    return AuthStatusResponse(message="Authenticated", owner_os_name=os_account_full_name())


router.include_router(pairing_router)
router.include_router(enrollment_routes.router)
router.include_router(join_local_routes.router)
router.include_router(projects_routes.router)
router.include_router(project_clone_routes.router)
router.include_router(status_router)
router.include_router(config_routes.router)
router.include_router(workspace_settings_routes.router)
