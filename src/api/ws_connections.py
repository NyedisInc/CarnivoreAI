
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Optional, Set

import structlog
from fastapi import WebSocket

if TYPE_CHECKING:
    from src.core.sessions.registry import SessionRegistry

from src.core import viewer_fanout
from src.core.bounded_stream import OFFER_ACCEPTED, BoundedStream

logger = structlog.get_logger()


def _resolve_backend(registry: SessionRegistry, session_id: Optional[str]):
    if session_id:
        return registry.get_backend(session_id)
    return registry.current_backend()


class ConnectionManager:

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._streams: dict[int, BoundedStream] = {}
        self._session_connections: dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, stream=None):
        self.active_connections.add(websocket)
        if viewer_fanout.is_viewer_stream(stream):
            self._streams[id(websocket)] = stream
        logger.info("websocket_connected", total_connections=len(self.active_connections))

    def bind_session(self, websocket: WebSocket, session_id: Optional[str]) -> None:
        if not session_id:
            return
        self._session_connections.setdefault(session_id, set()).add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        self._streams.pop(id(websocket), None)
        for sid, conns in list(self._session_connections.items()):
            conns.discard(websocket)
            if not conns:
                self._session_connections.pop(sid, None)
        logger.info("websocket_disconnected", total_connections=len(self.active_connections))

    async def broadcast(self, message: str):
        for connection in self.active_connections.copy():
            if not self._offer(connection, message):
                self.active_connections.discard(connection)
                self._streams.pop(id(connection), None)

    async def broadcast_to_session(self, session_id: str, message: str) -> int:
        sent = 0
        conns = self._session_connections.get(session_id)
        if not conns:
            return 0
        for connection in list(conns):
            if self._offer(connection, message):
                sent += 1
            else:
                logger.warning(
                    "broadcast_to_session_undeliverable",
                    session_id=session_id,
                )
                conns.discard(connection)
                self.active_connections.discard(connection)
                self._streams.pop(id(connection), None)
        if not conns:
            self._session_connections.pop(session_id, None)
        return sent

    def _offer(self, websocket: WebSocket, message: str) -> bool:
        stream = self._streams.get(id(websocket))
        if stream is None:
            return False
        return viewer_fanout.offer_text(stream, message) == OFFER_ACCEPTED



connection_manager = ConnectionManager()
