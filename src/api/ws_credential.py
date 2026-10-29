
from __future__ import annotations

import structlog
from fastapi import WebSocket

from src.api import peer_ws_auth
from src.api.deps import SUBPROTOCOL_MARKER, verify_jwt_from_subprotocol

logger = structlog.get_logger()


async def handshake(websocket: WebSocket, allow_peer: bool = False) -> bool:
    peer = await peer_ws_auth.try_peer(websocket) if allow_peer else None
    if peer is not None:
        return peer
    ok, detail = verify_jwt_from_subprotocol(websocket)
    if not ok:
        # header present
        raw_header = websocket.headers.get("sec-websocket-protocol")
        header_present_but_empty = (
            raw_header is not None
            and (
                not raw_header.strip()
                or all(not p.strip() for p in raw_header.split(","))
            )
        )
        code = 4400 if header_present_but_empty else 4401
        logger.warning(
            "websocket_auth_failed",
            reason=detail,
            close_code=code,
            has_header=raw_header is not None,
        )
        await websocket.close(code=code, reason=detail or "auth failed")
        return False

    await websocket.accept(subprotocol=SUBPROTOCOL_MARKER)
    return True


