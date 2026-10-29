"""Signed, short-lived link tickets for a plugin route that cannot carry the app's bearer token (an ``<iframe src>``, a pop-out window).

A plugin's authenticated route mints a ticket naming a few fields (an item id, a file id); a second route accepts only that ticket. It is an
HMAC-SHA256 over ``label|fields|expiry``, keyed from the server's JWT secret under the plugin's own ``label`` (so a ticket can never be
replayed as an access token, or for another purpose). Nothing is stored: a ticket is valid until its expiry and grants only what its fields name.

Example: mint("huddle-artifact", ["7", "49759e95"], 3600) -> "7.49759e95.1760000000.<sig>"; verify("huddle-artifact", that, 2) -> ("7", "49759e95")
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Optional, Sequence, Tuple

from fastapi import HTTPException

from src.config import settings


class SigningUnavailable(HTTPException):

    def __init__(self) -> None:
        super().__init__(status_code=503, detail={"code": "signing_unavailable", "detail": "no signing secret is configured"})


def _key(label: str) -> bytes:
    secret = settings.load_auth_config().jwt_secret
    if not secret:
        raise SigningUnavailable()
    return hashlib.sha256(f"{label}|".encode("utf-8") + secret.encode("utf-8")).digest()


def _sign(label: str, fields: Sequence[str], expiry: int) -> str:
    mac = hmac.new(_key(label), "|".join([*fields, str(expiry)]).encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode("ascii").rstrip("=")


def mint(label: str, fields: Sequence[str], ttl_s: int, now: Optional[float] = None) -> str:
    if any(("." in f or "|" in f or not f) for f in fields):
        raise ValueError("ticket fields are non-empty and contain no '.' or '|'")
    expiry = int((time.time() if now is None else now) + ttl_s)
    return ".".join([*fields, str(expiry), _sign(label, fields, expiry)])


def verify(label: str, ticket: str, count: int, now: Optional[float] = None) -> Optional[Tuple[str, ...]]:
    parts = (ticket or "").split(".")
    if len(parts) != count + 2 or not parts[-2].isdigit() or not all(parts[:count]):
        return None
    fields, expiry, sig = tuple(parts[:count]), int(parts[-2]), parts[-1]
    if not hmac.compare_digest(sig.encode("ascii", "ignore"), _sign(label, fields, expiry).encode("ascii")):
        return None
    return fields if (time.time() if now is None else now) < expiry else None
