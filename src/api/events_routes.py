
from __future__ import annotations

import asyncio
import json
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from src.api import peer_ws_auth, ws_dead_token
from src.api.deps import SUBPROTOCOL_MARKER, verify_jwt_from_subprotocol
from src.core.bounded_stream import BoundedStream
from src.core.event_hub import (
    EVENTS_OVERFLOW_CLOSE_CODE,
    EventClient,
    EventHub,
)
from src.core.federation import peer_sockets
from src.core.perf_hooks.monitor import PERF, frame_topic
from src.core.resource_push.topics import all_topics
from src.core.version import resolve_version
from src.core.static_asset_keys import client_build_key
from src.models import WSMessageType

logger = structlog.get_logger()

router = APIRouter()

_PONG_FRAME = json.dumps({"type": WSMessageType.PONG})

PEER_LISTING_QUERY = ("listing", "push")
PEER_FRAME_TYPES = frozenset({
    WSMessageType.EVENTS_HELLO.value, WSMessageType.PONG.value,
    WSMessageType.SESSION_STATUS_CHANGED.value, WSMessageType.TOAST_NEW.value,
    WSMessageType.PEER_LISTING.value})


def peer_may_receive(frame: str) -> bool:
    try:
        parsed = json.loads(frame)
    except ValueError:
        return False
    if not isinstance(parsed, dict) or parsed.get("type") not in PEER_FRAME_TYPES:
        return False
    toast = parsed.get("toast")
    named = parsed.get("session_id") or (toast.get("session_id") if isinstance(toast, dict) else None)
    return not (isinstance(named, str) and named.startswith("remote:"))


def _auth_close_code(websocket: WebSocket) -> int:
    raw_header = websocket.headers.get("sec-websocket-protocol")
    header_present_but_empty = (
        raw_header is not None
        and (
            not raw_header.strip()
            or all(not part.strip() for part in raw_header.split(","))
        )
    )
    return 4400 if header_present_but_empty else 4401


async def _drain_to_socket(websocket: WebSocket, stream: BoundedStream, peer: bool = False) -> str:
    while True:
        frame = await stream.get()
        if frame is None:
            return "overflow" if stream.overflowed else "done"
        if peer and not peer_may_receive(frame):
            continue
        try:
            await websocket.send_text(frame)
            if PERF.enabled:
                PERF.record_ws("events", frame_topic(frame), len(frame), stream.label)
        except (WebSocketDisconnect, RuntimeError) as exc:
            logger.debug("events_send_failed", error=str(exc))
            return "done"


async def _read_from_socket(websocket: WebSocket, stream: BoundedStream) -> None:
    while True:
        try:
            message = await websocket.receive()
        except (WebSocketDisconnect, RuntimeError):
            return
        if message.get("type") == "websocket.disconnect":
            return
        text = message.get("text")
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            logger.debug("events_bad_json_ignored")
            continue
        if isinstance(parsed, dict) and parsed.get("type") == WSMessageType.PING:
            stream.offer(_PONG_FRAME, len(_PONG_FRAME))


def _client_of(websocket: WebSocket) -> Optional[str]:
    return websocket.client.host if websocket.client else None


async def _refuse_known_dead_token(websocket: WebSocket) -> bool:
    token = ws_dead_token.presented_token(websocket.headers.get("sec-websocket-protocol"), SUBPROTOCOL_MARKER)
    client = _client_of(websocket)
    if token is None or not ws_dead_token.DEAD_TOKENS.seen(token, client):
        return False
    ws_dead_token.DEAD_TOKENS.refused(token, client)
    await websocket.close(code=4401, reason="invalid token")
    return True


def _log_auth_failure(websocket: WebSocket, detail: Optional[str], code: int) -> None:
    raw = websocket.headers.get("sec-websocket-protocol")
    token = ws_dead_token.presented_token(raw, SUBPROTOCOL_MARKER)
    client = _client_of(websocket)
    repeats = 0
    if token is not None:
        verdict = ws_dead_token.DEAD_TOKENS.refused(token, client)
        if not verdict.log:
            return
        repeats = verdict.repeats
    logger.warning(
        "events_websocket_auth_failed",
        reason=detail,
        close_code=code,
        has_header=raw is not None,
        client_ip=client,
        origin=websocket.headers.get("origin"),
        user_agent=ws_dead_token.short_agent(websocket.headers.get("user-agent")),
        repeats=repeats,
        repeat_window_s=int(ws_dead_token.WINDOW_S),
    )


@router.websocket("/ws/events", dependencies=[Depends(peer_ws_auth.peer_ws_marker)])
async def websocket_events(websocket: WebSocket) -> None:
    """The application event channel: one authenticated socket per browser.

    Description: verifies the JWT BEFORE accepting, so an unauthenticated
      client never establishes a connection at all (FastAPI turns a
      pre-accept close into an HTTP 403 and the browser's handshake
      fails). Registers on the hub, sends `events.hello`, then runs
      exactly two tasks: the one writer and the reader. Whichever finishes
      first ends the connection.
    Inputs: websocket (WebSocket).
    Output: None.
    """
    verdict = await peer_ws_auth.try_peer(websocket)
    if verdict is False:
        return
    peer = verdict is True
    if not peer and await _refuse_known_dead_token(websocket):
        return
    ok, detail = (True, "") if peer else verify_jwt_from_subprotocol(websocket)
    if not ok:
        code = _auth_close_code(websocket)
        _log_auth_failure(websocket, detail, code)
        await websocket.close(code=code, reason=detail or "auth failed")
        return

    hub: Optional[EventHub] = getattr(websocket.app.state, "event_hub", None)
    if hub is None:
        logger.warning("events_websocket_no_hub")
        await websocket.close(code=1011, reason="event hub unavailable")
        return

    if not peer:
        await websocket.accept(subprotocol=SUBPROTOCOL_MARKER)

    client: EventClient = hub.register(reduced=peer or bool(websocket.scope.get("via_link") or websocket.scope.get("via_peer_link")))
    hello = json.dumps({"type": WSMessageType.EVENTS_HELLO,
                        "client_id": client.client_id,
                        "server_version": resolve_version(),
                        "client_build": client_build_key(),
                        "resource_topics": list(all_topics())})
    client.stream.offer(hello, len(hello))
    feed = (getattr(websocket.app.state, "peer_listing_feed", None)
            if peer and websocket.query_params.get(PEER_LISTING_QUERY[0]) == PEER_LISTING_QUERY[1] else None)
    verdict = "done"
    try:
        if feed is not None:
            try:
                await feed.attach(client.stream)
            except Exception:  # noqa: BLE001
                logger.exception("peer_listing_feed_attach_failed")
        writer = asyncio.create_task(_drain_to_socket(websocket, client.stream, peer))
        reader = asyncio.create_task(_read_from_socket(websocket, client.stream))
        done, pending = await asyncio.wait(
            [writer, reader], return_when=asyncio.FIRST_COMPLETED
        )
        if writer in done and not writer.cancelled():
            verdict = writer.result()
        for task in pending:
            task.cancel()
    except WebSocketDisconnect:
        logger.debug("events_client_disconnected", client_id=client.client_id)
    finally:
        if feed is not None:
            feed.detach(client.stream)
        hub.unregister(client)
        grant = websocket.scope.get("peer_grant")
        if grant is not None:
            peer_sockets.unregister(grant.grant_id, websocket)

    if verdict == "overflow":
        logger.warning(
            "events_client_closed_overflow",
            client_id=client.client_id,
            close_code=EVENTS_OVERFLOW_CLOSE_CODE,
        )
        try:
            await websocket.close(
                code=EVENTS_OVERFLOW_CLOSE_CODE, reason="event queue overflow"
            )
        except RuntimeError:
            pass
