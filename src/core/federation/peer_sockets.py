
from __future__ import annotations

from typing import Any, Dict, List, Set

import structlog
from starlette.websockets import WebSocketState

logger = structlog.get_logger()

PEER_REVOKED_CODE = 4412
PEER_REVOKED_REASON = "peer_revoked"

_open: Dict[str, Set[Any]] = {}


def register(grant_id: str, websocket: Any) -> None:
    held = _open.setdefault(grant_id, set())
    held.difference_update({w for w in held if getattr(w, "application_state", None) == WebSocketState.DISCONNECTED})
    held.add(websocket)


def unregister(grant_id: str, websocket: Any) -> None:
    held = _open.get(grant_id)
    if held is not None:
        held.discard(websocket)
        if not held:
            del _open[grant_id]


def count(grant_id: str) -> int:
    return len(_open.get(grant_id, ()))


async def close_grant(grant_id: str) -> int:
    held: List[Any] = list(_open.pop(grant_id, ()))
    closed = 0
    for websocket in held:
        try:
            await websocket.close(code=PEER_REVOKED_CODE, reason=PEER_REVOKED_REASON)
            closed += 1
        except (RuntimeError, OSError) as exc:
            logger.info("peer_socket_close_skipped", error_type=type(exc).__name__)
    return closed
