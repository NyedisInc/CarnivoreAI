
import asyncio
import base64
import io
import os
import secrets
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import jwt
import pyotp
import qrcode
import structlog
from cachetools import TTLCache
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.config import settings, ProjectConfig
from src.core.api_keys import gate as api_key_gate, store as api_key_store
from src.api import projects_service
from src.models import (
    VerifyTOTPRequest,
    AuthTokenResponse,
    ProjectResponse,
    CreateProjectRequest,
    UpdateProjectRequest,
    CloneProjectRequest,
    SuccessResponse,
    ConfigSettingsUpdateRequest,
    ToggleFavoriteCommandRequest,
)
from src.core.workspace_settings import (
    WorkspaceValidationError,
    validate_bind_host,
    validate_development_root,
    validate_editor,
    validate_env_map,
    validate_shell,
)
from src.core.slash_command_discovery import build_command_groups, command_groups_to_dict
from src.core import slash_command_labels, slash_favorites
def _totp_paired_sentinel_path() -> Path:
    return Path(settings.auth_config_file).expanduser().parent / ".totp_paired"

logger = structlog.get_logger()

security = HTTPBearer(auto_error=False)


def _rate_limit_key(request: Request) -> str:
    if request.scope.get("via_link"):
        return get_remote_address(request)
    try:
        trust_proxy = settings.load_auth_config().auth_rate_limits.trust_proxy_headers
    except Exception:
        trust_proxy = False

    if trust_proxy:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            first = xff.split(",")[0].strip()
            if first:
                return first
    return get_remote_address(request)


limiter = Limiter(key_func=_rate_limit_key, headers_enabled=True)


def _totp_rate_limit() -> str:
    try:
        cfg = settings.load_auth_config().auth_rate_limits
        return f"{cfg.totp_verify_per_minute}/minute;{cfg.totp_verify_per_hour}/hour"
    except Exception:
        return "5/minute;20/hour"


_TOTP_REPLAY_TTL = 90
_totp_seen_cache: TTLCache = TTLCache(maxsize=1000, ttl=_TOTP_REPLAY_TTL)
_totp_seen_lock = asyncio.Lock()


def _get_ttls() -> tuple[int, int, int]:
    auth_config = settings.load_auth_config()
    access_ttl = int(getattr(auth_config, "access_token_ttl_seconds", 14400))
    refresh_ttl = int(getattr(auth_config, "refresh_token_ttl_seconds", 604800))
    grace = int(getattr(auth_config, "refresh_grace_seconds", 10))
    return access_ttl, refresh_ttl, grace


def create_access_token(user: str = "claudetunnel_user") -> tuple[str, int]:
    auth_config = settings.load_auth_config()
    access_ttl, _, _ = _get_ttls()
    now = datetime.utcnow()
    payload = {
        "exp": now + timedelta(seconds=access_ttl),
        "iat": now,
        "sub": user,
        "typ": "access",
    }
    token = jwt.encode(payload, auth_config.jwt_secret, algorithm="HS256")
    return token, access_ttl


def create_refresh_token(
    user: str = "claudetunnel_user",
) -> tuple[str, str, int]:
    auth_config = settings.load_auth_config()
    _, refresh_ttl, _ = _get_ttls()
    jti = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    exp_dt = now + timedelta(seconds=refresh_ttl)
    payload = {
        "exp": exp_dt,
        "iat": now,
        "sub": user,
        "typ": "refresh",
        "jti": jti,
    }
    token = jwt.encode(payload, auth_config.jwt_secret, algorithm="HS256")
    return token, jti, int(exp_dt.timestamp())




def create_jwt_token(expiry_minutes: Optional[int] = None) -> tuple[str, int]:
    token, ttl_seconds = create_access_token()
    return token, ttl_seconds


def verify_jwt_token(token: str) -> bool:
    try:
        decode_access_token(token)
        return True
    except HTTPException:
        return False
    except Exception as e:
        logger.error("token_verification_error", error=str(e))
        return False


def _decode_with_typ(token: str, expected_typ: str) -> dict:
    try:
        auth_config = settings.load_auth_config()
    except Exception as e:
        logger.error("auth_config_load_failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Authentication not configured.",
        )

    try:
        claims = jwt.decode(
            token,
            auth_config.jwt_secret,
            algorithms=["HS256"],
        )
    except jwt.ExpiredSignatureError:
        logger.debug("token_expired", typ=expected_typ)
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        logger.debug("token_invalid", error=str(e), typ=expected_typ)
        raise HTTPException(status_code=401, detail="Invalid token")

    if claims.get("typ") != expected_typ:
        logger.warning(
            "token_wrong_typ",
            got=claims.get("typ"),
            expected=expected_typ,
        )
        raise HTTPException(status_code=401, detail="Invalid token type")

    return claims


def decode_access_token(token: str) -> dict:
    return _decode_with_typ(token, "access")


def decode_refresh_token(token: str) -> dict:
    return _decode_with_typ(token, "refresh")


async def require_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    request: Request = None,
) -> bool:
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Please log in with your TOTP code.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    if api_key_store.is_api_key(credentials.credentials):
        await api_key_gate.admit(credentials.credentials, request)
        return True

    try:
        decode_access_token(credentials.credentials)
    except HTTPException as e:
        raise HTTPException(
            status_code=401,
            detail=e.detail if isinstance(e.detail, str) else "Invalid or expired authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return True
