
from __future__ import annotations

import asyncio
import json
from contextlib import closing
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote, urlencode

import structlog
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect
from websockets.asyncio.client import connect, unix_connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, WebSocketException

from src.api import peer_auth
from src.api.deps import SUBPROTOCOL_MARKER
from src.core.federation import mesh_peers, peer_hosts, peer_links, peer_listing
from src.core.federation.peer_client import PeerClient, PeerRefused, PeerUnreachable
from src.core.federation.peer_sockets import PEER_REVOKED_CODE, PEER_REVOKED_REASON
from src.core.hosts.identity import parse_remote_session_id
from src.core.viewer_fanout import VIEWER_OVERFLOW_CLOSE_CODE
from src.models import WSMessageType

logger = structlog.get_logger()

PEER_UNAVAILABLE_CODE = 4502
PEER_UNAVAILABLE_REASON = "peer_unavailable"
UNKNOWN_SESSION_CODE = 4404
MAX_FRAME_BYTES = 4 * 1024 * 1024
MAX_CONTROL_BYTES = 4096
CONNECT_TIMEOUT = 5.0
MEASURE_GRACE = 1.5
RESIZE_SETTLE = 0.6
FORWARDED_QUERY = ("client_id", "observer", "interactive")

DOWN_TYPES = frozenset({
    WSMessageType.REQUEST_DIMS.value, WSMessageType.TERMINAL_READY.value, WSMessageType.TERMINAL_RESYNC.value,
    WSMessageType.TERMINAL_SIZE.value,
    WSMessageType.SIZE_MASTER.value, WSMessageType.PONG.value, WSMessageType.ERROR.value})
UP_TYPES: Dict[str, Tuple[str, ...]] = {
    WSMessageType.PTY_RESIZE.value: ("cols", "rows", "hidden"),
    WSMessageType.VIEWER_FOCUS.value: ("focused",),
    WSMessageType.REPAINT.value: (),
    WSMessageType.PAUSE.value: (),
    WSMessageType.RESUME.value: (),
    WSMessageType.PING.value: (),
}


def down_text(raw: str, wire_id: str) -> Optional[str]:
    try:
        msg = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(msg, dict) or msg.get("type") not in DOWN_TYPES:
        return None
    if msg["type"] == WSMessageType.SIZE_MASTER.value and "session_id" in msg:
        msg["session_id"] = wire_id
    return json.dumps(msg)


def up_text(raw: str) -> Optional[str]:
    if len(raw) > MAX_CONTROL_BYTES:
        return None
    try:
        msg = json.loads(raw)
    except ValueError:
        return None
    fields = UP_TYPES.get(msg.get("type")) if isinstance(msg, dict) else None
    if fields is None:
        return None
    return json.dumps({"type": msg["type"], **{k: msg[k] for k in fields if k in msg}})


def close_for(code: Optional[int]) -> Tuple[int, str]:
    if code == PEER_REVOKED_CODE:
        return PEER_REVOKED_CODE, PEER_REVOKED_REASON
    if code in (UNKNOWN_SESSION_CODE, VIEWER_OVERFLOW_CLOSE_CODE):
        return int(code), "peer_session" if code == UNKNOWN_SESSION_CODE else "viewer queue overflow"
    if code in (1000, 1001):
        return 1000, ""
    return PEER_UNAVAILABLE_CODE, PEER_UNAVAILABLE_REASON


def _peer_client(host_key: str) -> Optional[PeerClient]:
    links = peer_links.LINKS
    connected = mesh_peers.session_clients(links)
    if not connected:
        return None
    with closing(peer_auth.open_db()) as conn:
        for install_id, client in connected:
            row = peer_hosts.get(conn, install_id, include_mesh=True)
            if row is not None and row.key == host_key:
                return client
    return None


def _upstream_url(name: str, query: Any) -> str:
    params = {"session_id": name, **{k: query[k] for k in FORWARDED_QUERY if k in query}}
    return "/ws/terminal?" + urlencode(params)


async def _open(client: PeerClient, url: str, token: str):
    options: Dict[str, Any] = dict(subprotocols=[SUBPROTOCOL_MARKER, token], max_size=MAX_FRAME_BYTES,
                                   compression=None, open_timeout=CONNECT_TIMEOUT)
    if client.route.kind == "unix":
        return await unix_connect(str(client.route.target), "ws://127.0.0.1" + url, **options)
    return await connect("ws://127.0.0.1" + url, sock=await client.proven_socket(), **options)


async def connect_upstream(client: PeerClient, url: str):
    for attempt in (0, 1):
        try:
            return await _open(client, url, await client.bearer(force=bool(attempt)))
        except (PeerUnreachable, PeerRefused, OSError, asyncio.TimeoutError, WebSocketException) as exc:
            logger.info("peer_upstream_socket_failed", url=url.split("?")[0], attempt=attempt,
                        error_type=type(exc).__name__, error=str(exc)[:160])
            if attempt:
                raise PeerUnavailable() from None
    raise PeerUnavailable()


class PeerUnavailable(Exception):
    pass


class _Measure:

    def __init__(self, client: PeerClient, host_key: str, name: str) -> None:
        self.client = client
        self.host_key = host_key
        self.name = name
        self.owner_sends = False
        self.tasks: set = set()

    def schedule(self, websocket: WebSocket, delay: float) -> None:
        if self.owner_sends:
            return
        task = asyncio.create_task(self._read(websocket, delay))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _read(self, websocket: WebSocket, delay: float) -> None:
        await asyncio.sleep(delay)
        if self.owner_sends:
            return
        frame = await measured_frame_from_peer(self.client, peer_listing.owner_session_id(self.host_key, self.name) or self.name)
        if frame is not None and not self.owner_sends:
            try:
                await websocket.send_text(frame)
            except (WebSocketDisconnect, RuntimeError):
                pass

    def cancel(self) -> None:
        for task in list(self.tasks):
            task.cancel()


async def measured_frame_from_peer(client: PeerClient, owner_id: str) -> Optional[str]:
    try:
        response = await client.request("GET", f"/sessions/{quote(owner_id, safe='')}/pane-facts", timeout=CONNECT_TIMEOUT)
    except (PeerUnreachable, PeerRefused):
        return None
    data = _json_or_empty(response) if response.status_code == 200 else {}
    cols = data.get("cols") if isinstance(data, dict) else None
    rows = data.get("rows") if isinstance(data, dict) else None
    if not (isinstance(cols, int) and isinstance(rows, int) and not isinstance(cols, bool) and not isinstance(rows, bool)
            and 1 <= cols <= 1000 and 1 <= rows <= 1000):
        return None
    return json.dumps({"type": WSMessageType.TERMINAL_SIZE.value, "cols": cols, "rows": rows, "measured": True})


async def _up(websocket: WebSocket, upstream: Any, measure: _Measure) -> None:
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
        if message.get("bytes") is not None:
            await upstream.send(message["bytes"])
        elif message.get("text") is not None:
            frame = up_text(message["text"])
            if frame is not None:
                await upstream.send(frame)
                sent = json.loads(frame)
                if sent["type"] == WSMessageType.PTY_RESIZE.value and not sent.get("hidden"):
                    measure.schedule(websocket, RESIZE_SETTLE)


async def _down(websocket: WebSocket, upstream: Any, wire_id: str, measure: _Measure) -> None:
    async for frame in upstream:
        if isinstance(frame, bytes):
            await websocket.send_bytes(frame)
            continue
        text = down_text(frame, wire_id)
        if text is not None:
            if '"measured"' in text and json.loads(text).get("measured") is True:
                measure.owner_sends = True
            await websocket.send_text(text)


async def dispatch(websocket: WebSocket, registry: Any, requested_sid: Optional[str]) -> bool:
    parsed = parse_remote_session_id(requested_sid)
    if (parsed is None or not parsed[0].startswith("peer-") or requested_sid in registry.sessions
            or websocket.scope.get("peer_grant") is not None):
        return False
    await relay(websocket, parsed[0], parsed[1], str(requested_sid))
    return True


def _mesh_iid(host_key: str) -> Optional[str]:
    from src.core.federation import peer_forward

    with closing(peer_auth.open_db()) as conn:
        row = peer_forward._peer_by_key(conn, host_key)
    return row.peer_install_id if row is not None and row.back_kind == peer_hosts.MESH_BACK_KIND else None


async def _client_for(host_key: str) -> Tuple[Optional[PeerClient], Optional[str]]:
    client = _peer_client(host_key)
    if mesh_peers.REGISTRY is None:
        return client, None
    iid = await asyncio.to_thread(_mesh_iid, host_key)
    if client is not None or iid is None:
        return client, iid
    return await mesh_peers.connect(peer_links.LINKS, iid), iid


async def relay(websocket: WebSocket, host_key: str, name: str, wire_id: str) -> None:
    client, mesh_iid = await _client_for(host_key)
    keep = mesh_peers.keep_alive(mesh_iid) if mesh_iid is not None and client is not None else None
    upstream = None
    measure: Optional[_Measure] = None
    try:
        if client is None:
            raise PeerUnavailable()
        upstream = await connect_upstream(client, _upstream_url(name, websocket.query_params))
        measure = _Measure(client, host_key, name)
        measure.schedule(websocket, MEASURE_GRACE)
        tasks = [asyncio.create_task(_up(websocket, upstream, measure)), asyncio.create_task(_down(websocket, upstream, wire_id, measure))]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            task.result()
        if tasks[1] in done:
            rcvd = upstream.close_rcvd
            await _close_browser(websocket, *close_for(rcvd.code if rcvd is not None else None))
    except PeerUnavailable:
        await _close_browser(websocket, PEER_UNAVAILABLE_CODE, PEER_UNAVAILABLE_REASON)
    except ConnectionClosed as exc:
        await _close_browser(websocket, *close_for(exc.rcvd.code if exc.rcvd is not None else None))
    except (WebSocketDisconnect, RuntimeError):
        pass
    except (OSError, WebSocketException):
        await _close_browser(websocket, PEER_UNAVAILABLE_CODE, PEER_UNAVAILABLE_REASON)
    finally:
        if keep is not None:
            keep.cancel()
        if measure is not None:
            measure.cancel()
        if upstream is not None:
            await upstream.close()


async def _close_browser(websocket: WebSocket, code: int, reason: str) -> None:
    try:
        await websocket.close(code=code, reason=reason)
    except RuntimeError:
        pass


def _json_or_empty(response: Any) -> Any:
    try:
        return response.json()
    except ValueError:
        return {}


async def forward_crown(host_key: str, name: str, method: str, wire_id: str,
                        body: Optional[dict] = None, client_id: Optional[str] = None) -> Any:
    client, _ = await _client_for(host_key)
    if client is None:
        raise PeerUnavailable()
    path = f"/sessions/{quote(name, safe='')}/size-master" + (f"?{urlencode({'client_id': client_id})}" if client_id else "")
    try:
        response = await client.request(method, path, json=body)
    except (PeerUnreachable, PeerRefused):
        raise PeerUnavailable() from None
    data = _json_or_empty(response) if response.status_code < 500 else {}
    if isinstance(data, dict) and "session_id" in data:
        data["session_id"] = wire_id
    return response.status_code, data
