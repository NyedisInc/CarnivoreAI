
from __future__ import annotations

import time
from typing import Any, Dict

import structlog
from fastapi import HTTPException

from src.api.auth import create_access_token, create_refresh_token
from src.api.auth_routes import check_totp_code
from src.core.federation.pairing import KeyedWindows

logger = structlog.get_logger()

_MINUTE = KeyedWindows(5, 60.0)
_HOUR = KeyedWindows(20, 3600.0)
_LIMITER_KEY = "door"


async def door_totp_ok(code: str) -> bool:
    now = time.monotonic()
    if not (_MINUTE.hit(_LIMITER_KEY, now) and _HOUR.hit(_LIMITER_KEY, now)):
        logger.warning("door_totp_rate_limited")
        return False
    try:
        await check_totp_code(code)
    except HTTPException:
        return False
    except FileNotFoundError:
        return False
    return True


async def door_login_tokens(refresh_store: Any) -> Dict[str, Any]:
    access, expires_in = create_access_token()
    refresh, jti, exp = create_refresh_token()
    if refresh_store is not None:
        try:
            await refresh_store.issue(jti, "claudetunnel_user", exp)
        except Exception as exc:  # noqa: BLE001
            logger.error("door_login_store_failed", error_type=type(exc).__name__)
            raise RuntimeError("refresh store failed") from None
    return {"access_token": access, "refresh_token": refresh, "expires_in": expires_in}
