
from fastapi import HTTPException, WebSocket
from typing import Optional, Tuple
import structlog

from src.api.auth import decode_access_token

logger = structlog.get_logger()


SUBPROTOCOL_MARKER = "cloude.jwt.v1"

def _parse_subprotocols(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


def verify_jwt_from_subprotocol(websocket: WebSocket) -> Tuple[bool, Optional[str]]:
    raw = websocket.headers.get("sec-websocket-protocol")
    protocols = _parse_subprotocols(raw)

    if not protocols:
        return False, "missing subprotocol"

    if SUBPROTOCOL_MARKER not in protocols:
        return False, "missing subprotocol"

    others = [p for p in protocols if p != SUBPROTOCOL_MARKER]

    if not others:
        return False, "missing token"

    token = others[0]

    if not token:
        return False, "missing token"

    try:
        decode_access_token(token)
    except HTTPException:
        return False, "invalid token"

    return True, token
