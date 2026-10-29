
from __future__ import annotations

from typing import Any, Dict, Optional

from src.core.catalog.token_store import CatalogSession

__all__ = [
    "ACCESS_SKEW_SECONDS",
    "ROTATE",
    "SIGNED_OUT",
    "USE_ACCESS",
    "is_session_revoked",
    "session_from_refresh",
    "token_action",
]

ACCESS_SKEW_SECONDS = 60

USE_ACCESS = "access"

ROTATE = "refresh"

SIGNED_OUT = "none"


def token_action(session: Optional[CatalogSession], now: int) -> str:
    if session is None:
        return SIGNED_OUT
    floor = now + ACCESS_SKEW_SECONDS
    if session.access_expires_at > floor:
        return USE_ACCESS
    if session.refresh_expires_at > floor:
        return ROTATE
    return SIGNED_OUT


def _seconds(body: Dict[str, Any], key: str) -> int:
    value = body.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(int(value), 0)


def _token(body: Dict[str, Any], key: str) -> Optional[str]:
    value = body.get(key)
    if not isinstance(value, str) or not value:
        return None
    return value


def session_from_refresh(
    body: Dict[str, Any], *, fallback_login: str, now: int, provider: Optional[str] = None
) -> Optional[CatalogSession]:
    access = _token(body, "access_token")
    refresh = _token(body, "refresh_token")
    if access is None or refresh is None:
        return None
    login = _token(body, "login") or fallback_login
    return CatalogSession(
        login=login,
        access_token=access,
        access_expires_at=now + _seconds(body, "expires_in"),
        refresh_token=refresh,
        refresh_expires_at=now + _seconds(body, "refresh_expires_in"),
        provider=provider,
    )


def is_session_revoked(status: int, body: Dict[str, Any]) -> bool:
    """Whether a hosted answer says this device's session was signed out remotely.

    Description: the hosted api answers 401 ``session_revoked`` when the
      session named by the access or refresh token was revoked from another
      device, signed out, expired at its 180 day end or reused after
      rotation. The stored pair is then worthless, so the caller clears it
      and reads as signed out rather than retrying a credential that can
      never work again. A plain 401 ``unauthorized`` is NOT this: it may be
      a token the host merely could not verify.
    Inputs: status (int); body (dict) the hosted answer body.
    Output: bool.
    Example: is_session_revoked(401, {"code": "session_revoked"})  # True
    """
    return status == 401 and isinstance(body, dict) and body.get("code") == "session_revoked"
