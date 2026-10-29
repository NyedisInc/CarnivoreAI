
from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException, WebSocket

from src.api import peer_auth
from src.api.deps import SUBPROTOCOL_MARKER, _parse_subprotocols
from src.core.federation import peer_sockets, peer_token
from src.core.hosts.identity import is_remote_backend

NOT_LOCAL = "peer:not-local"


def peer_ws_marker() -> None:
    pass


peer_ws_marker.peer_scope = "sessions"  # type: ignore[attr-defined]


async def try_peer(websocket: WebSocket) -> Optional[bool]:
    offered = _parse_subprotocols(websocket.headers.get("sec-websocket-protocol"))
    others = [p for p in offered if p != SUBPROTOCOL_MARKER]
    if SUBPROTOCOL_MARKER not in offered or not others or not peer_token.is_peer_token(others[0]):
        return None
    if websocket.scope.get("via_link"):
        await websocket.close(code=4401, reason="invalid token")
        return False
    try:
        grant = (await peer_auth._authorize_peer(others[0], "sessions")).grant
        await peer_auth.enforce_direction(websocket.url.path, grant)
    except HTTPException:
        await websocket.close(code=4401, reason="invalid token")
        return False
    await websocket.accept(subprotocol=SUBPROTOCOL_MARKER)
    websocket.scope["peer_grant"] = grant
    peer_sockets.register(grant.grant_id, websocket)
    return True


def local_session_id(registry: Any, ident: Optional[str]) -> str:
    if not ident:
        return NOT_LOCAL
    for sid in ([ident] if ident in registry.sessions else []) + list(registry.registered_ids_for_tmux_name(ident)):
        if sid in registry.sessions and not is_remote_backend(registry.get_backend(sid)):
            return sid
    return NOT_LOCAL
