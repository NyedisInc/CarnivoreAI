
from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import json
import time
from collections import deque
from typing import Any, Awaitable, Callable, Deque, Dict, List, Optional, Protocol

import structlog
import websockets
from websockets.exceptions import ConnectionClosed, InvalidStatus, WebSocketException

from src.core import relay_protocol as proto
from src.core.phone_link import frames
from src.core.phone_link.custom_domain import hello as tls_hello
from src.core.phone_link.gate import LinkStream, StreamTable
from src.core.relay_identity.session import (
    REFRESH_MARGIN_SECONDS,
    DeviceSession,
    RelayAuthError,
)

logger = structlog.get_logger()

SUBPROTOCOL = "carnivore.link.tunnel.v1"
MAX_FRAMES_PER_SECOND = 800
PRE_AUTH_SECONDS = 10.0
GRANT_BATCH = 32 * 1024
STABLE_SECONDS = 30.0
MAX_STREAMS = 64
COALESCE_BYTES = 4096
COALESCE_WAIT_SECONDS = 0.002
REAUTH_RETRY_SECONDS = 30.0
CLOSE_REPLACED, CLOSE_DENIED, CLOSE_TOO_OLD = 4409, 4403, 4426

Connect = Callable[..., Any]
OpenLocal = Callable[[], Awaitable[Any]]


class CustomRouting(Protocol):

    def name(self) -> Optional[str]:
        pass

    def ready(self) -> bool:
        pass

    def challenge_port(self) -> Optional[int]:
        pass


def public_client_ip(value: str) -> Optional[str]:
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    if (addr.is_loopback or addr.is_private or addr.is_link_local or addr.is_unspecified
            or addr.is_multicast or addr.is_reserved):
        return None
    return str(addr)


class _Stream:

    def __init__(self, sid: int, info: LinkStream, reader: Optional[asyncio.StreamReader],
                 writer: Optional[asyncio.StreamWriter], port: int) -> None:
        self.sid, self.info, self.reader, self.writer, self.port = sid, info, reader, writer, port
        self.credit = frames.INITIAL_WINDOW
        self.credit_event = asyncio.Event()
        self.credit_event.set()
        self.recv_credit = frames.INITIAL_WINDOW
        self.inbound: "asyncio.Queue[Optional[bytes]]" = asyncio.Queue()
        self.sent_close = False
        self.tasks: List["asyncio.Task[None]"] = []


class TunnelClient:

    def __init__(self, *, url: str, session: DeviceSession, local_port: Callable[[], int],
                 streams: StreamTable, custom: Optional[CustomRouting] = None,
                 connect: Connect = websockets.connect,
                 clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 client_ip_check: Callable[[str], Optional[str]] = public_client_ip) -> None:
        self._custom = custom
        self._client_ip_check = client_ip_check
        self._url, self._session, self._local_port = url, session, local_port
        self._table, self._connect, self._clock, self._sleep = streams, connect, clock, sleep
        self._task: Optional["asyncio.Task[None]"] = None
        self._out: Optional["asyncio.Queue[bytes]"] = None
        self._streams: Dict[int, _Stream] = {}
        self._held: Optional[Any] = None
        self.status = "stopped"

    @property
    def connected(self) -> bool:
        return self.status == "connected"

    def start(self) -> None:
        if self._task is None or self._task.done():
            self.status = "connecting"
            self._task = asyncio.create_task(self._run(), name="phone-link-tunnel")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        self.status = "stopped"


    def trust(self, stream_id: int) -> None:
        if self._out is not None and stream_id in self._streams:
            self._out.put_nowait(frames.pack(frames.TRUST, stream_id))

    def close_device(self, device_id: str) -> None:
        for stream in [s for s in self._streams.values() if s.info.device == device_id]:
            self._end(stream, frames.REASON_NORMAL)

    async def reauth_now(self) -> bool:
        if self._out is None:
            return False
        fresh = await self._session.token()
        self._out.put_nowait(frames.pack(frames.REAUTH, 0, json.dumps(await self._session.tunnel_reauth_payload(fresh)).encode()))
        self._held = fresh
        return True


    async def _run(self) -> None:
        attempt = 0
        while True:
            started = self._clock()
            try:
                terminal = await self._serve_once()
            except RelayAuthError as exc:
                logger.warning("phone_link_tunnel_auth_failed", kind=exc.kind)
                if exc.terminal or exc.parks:
                    self.status = exc.kind
                    return
                terminal = False
            except (OSError, WebSocketException, asyncio.TimeoutError) as exc:
                logger.warning("phone_link_tunnel_dial_failed", error=type(exc).__name__)
                terminal = False
            if terminal:
                return
            self.status = "connecting"
            attempt = 0 if self._clock() - started >= STABLE_SECONDS else attempt + 1
            await self._sleep(proto.backoff_delay(max(attempt - 1, 0)))

    async def _serve_once(self) -> bool:
        token = await self._session.token()
        headers = await self._session.pop_headers(token, tunnel=True)
        try:
            ws = await self._connect(self._url, additional_headers=headers, subprotocols=[SUBPROTOCOL],
                                     max_size=frames.MAX_PAYLOAD + 64, open_timeout=15)
        except InvalidStatus as exc:
            logger.warning("phone_link_tunnel_refused", status=exc.response.status_code)
            self._session.drop_token()
            return False
        self._out = asyncio.Queue()
        self.status = "connected"
        logger.info("phone_link_tunnel_connected")
        workers = [asyncio.create_task(self._writer(ws)), asyncio.create_task(self._reauth_supervised())]
        try:
            async for message in ws:
                if isinstance(message, bytes):
                    await self._on_frame(message)
        except ConnectionClosed:
            pass
        except frames.FrameError as exc:
            logger.warning("phone_link_tunnel_bad_frame", error=str(exc))
            await ws.close(4400)
        finally:
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            for stream in list(self._streams.values()):
                self._end(stream, frames.REASON_NORMAL, notify=False)
            self._out = None
            with contextlib.suppress(WebSocketException, OSError):
                await ws.close()
        code = ws.close_code
        logger.info("phone_link_tunnel_closed", code=code)
        if code == CLOSE_DENIED or code == CLOSE_TOO_OLD:
            self.status = "denied" if code == CLOSE_DENIED else "update_required"
            return True
        if code == 4401:
            self._session.drop_token()
        return False

    async def _writer(self, ws: Any) -> None:
        assert self._out is not None
        stamps: Deque[float] = deque()
        while True:
            frame = await self._out.get()
            now = time.monotonic()
            while stamps and stamps[0] <= now - 1.0:
                stamps.popleft()
            if len(stamps) >= MAX_FRAMES_PER_SECOND:
                await asyncio.sleep(stamps[0] + 1.0 - now)
            stamps.append(time.monotonic())
            await ws.send(frame)

    async def _reauth_supervised(self) -> None:
        while True:
            try:
                await self._reauth_loop()
            except Exception as exc:  # noqa: BLE001
                logger.warning("phone_link_reauth_loop_failed", error_type=type(exc).__name__)
                await self._sleep(REAUTH_RETRY_SECONDS)

    async def _reauth_loop(self) -> None:
        assert self._out is not None
        self._held = await self._session.token()
        while True:
            wait = self._held.exp - REFRESH_MARGIN_SECONDS - self._clock()
            if wait > 0:
                await self._sleep(wait + 1)
            fresh = await self._session.token()
            if fresh.exp <= self._held.exp:
                await self._sleep(30)
                continue
            payload = json.dumps(await self._session.tunnel_reauth_payload(fresh)).encode()
            self._out.put_nowait(frames.pack(frames.REAUTH, 0, payload))
            self._held = fresh


    async def _on_frame(self, raw: bytes) -> None:
        kind, sid, payload = frames.unpack(raw)
        if kind == frames.OPEN:
            await self._open(sid, payload)
            return
        stream = self._streams.get(sid)
        if stream is None:
            return
        if kind == frames.DATA:
            if not payload or len(payload) > stream.recv_credit:
                self._end(stream, frames.REASON_ERROR)
                return
            stream.recv_credit -= len(payload)
            stream.inbound.put_nowait(payload)
        elif kind == frames.WINDOW:
            stream.credit += frames.window_credit(payload)
            if stream.credit > frames.INITIAL_WINDOW:
                self._end(stream, frames.REASON_ERROR)
                return
            stream.credit_event.set()
        elif kind == frames.CLOSE:
            stream.inbound.put_nowait(None)

    async def _open(self, sid: int, payload: bytes) -> None:
        try:
            opened = json.loads(payload)
            ip, port_ = self._client_ip_check(str(opened["client_ip"])), int(opened["client_port"])
            sni = str(opened.get("sni") or "").lower().rstrip(".")
        except (ValueError, KeyError, TypeError, AttributeError):
            ip, port_, sni = None, 0, ""
        if ip is None or not 0 < port_ < 65536:
            self._send_close(sid, frames.REASON_ERROR)
            return
        if sid in self._streams:
            return
        if len(self._streams) >= MAX_STREAMS:
            logger.warning("phone_link_stream_cap", cap=MAX_STREAMS)
            self._send_close(sid, frames.REASON_LIMIT)
            return
        info = LinkStream(stream_id=sid, client_ip=ip, client_port=port_, sni=sni)
        custom_name = self._custom.name() if self._custom is not None else None
        if custom_name and sni == custom_name:
            stream = _Stream(sid, info, None, None, 0)
            self._streams[sid] = stream
            stream.tasks = [asyncio.create_task(self._route_custom(stream)),
                            asyncio.create_task(self._pre_auth_deadline(stream))]
            return
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", self._local_port())
        except OSError as exc:
            logger.warning("phone_link_local_connect_failed", error=type(exc).__name__)
            self._send_close(sid, frames.REASON_ERROR)
            return
        local = writer.get_extra_info("sockname")[1]
        self._table.add(local, info)
        stream = _Stream(sid, info, reader, writer, local)
        self._streams[sid] = stream
        stream.tasks = [asyncio.create_task(self._to_local(stream)),
                        asyncio.create_task(self._from_local(stream)),
                        asyncio.create_task(self._pre_auth_deadline(stream))]

    async def _route_custom(self, stream: _Stream) -> None:
        assert self._custom is not None
        head, hello = b"", None
        while hello is None:
            chunk = await stream.inbound.get()
            if chunk is None:
                self._end(stream, frames.REASON_NORMAL)
                return
            head += chunk
            try:
                hello = tls_hello.parse(head)
            except tls_hello.HelloError:
                self._end(stream, frames.REASON_ERROR)
                return
        challenge = hello.is_acme_challenge
        port = self._custom.challenge_port() if challenge else (self._local_port() if self._custom.ready() else None)
        if port is None or hello.sni != stream.info.sni:
            logger.info("phone_link_custom_stream_refused", challenge=challenge)
            self._end(stream, frames.REASON_ERROR)
            return
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
        except OSError as exc:
            logger.warning("phone_link_local_connect_failed", error=type(exc).__name__)
            self._end(stream, frames.REASON_ERROR)
            return
        stream.reader, stream.writer, stream.port = reader, writer, writer.get_extra_info("sockname")[1]
        if not challenge:
            self._table.add(stream.port, stream.info)
        try:
            writer.write(head)
            await writer.drain()
        except (ConnectionError, OSError):
            self._end(stream, frames.REASON_ERROR)
            return
        if self._out is not None:
            stream.recv_credit += len(head)
            self._out.put_nowait(frames.pack(frames.WINDOW, stream.sid, frames.window_payload(len(head))))
        stream.tasks += [asyncio.create_task(self._to_local(stream)), asyncio.create_task(self._from_local(stream))]


    def _send_close(self, sid: int, reason: int) -> None:
        if self._out is not None:
            self._out.put_nowait(frames.pack(frames.CLOSE, sid, bytes([reason])))

    def _end(self, stream: _Stream, reason: int, notify: bool = True) -> None:
        if self._streams.pop(stream.sid, None) is None:
            return
        if notify and not stream.sent_close:
            stream.sent_close = True
            self._send_close(stream.sid, reason)
        if stream.writer is not None:
            self._table.remove(stream.port)
            stream.writer.transport.abort()
        current = asyncio.current_task()
        for task in stream.tasks:
            if task is not current:
                task.cancel()

    async def _to_local(self, stream: _Stream) -> None:
        pending = 0
        while True:
            chunk = await stream.inbound.get()
            if chunk is None:
                with contextlib.suppress(OSError):
                    if not stream.writer.is_closing():
                        stream.writer.close()
                self._end(stream, frames.REASON_NORMAL)
                return
            try:
                stream.writer.write(chunk)
                await stream.writer.drain()
            except (ConnectionError, OSError):
                self._end(stream, frames.REASON_ERROR)
                return
            pending += len(chunk)
            if (stream.inbound.empty() or pending >= GRANT_BATCH) and self._out is not None:
                stream.recv_credit += pending
                self._out.put_nowait(frames.pack(frames.WINDOW, stream.sid, frames.window_payload(pending)))
                pending = 0

    async def _from_local(self, stream: _Stream) -> None:
        while True:
            while stream.credit <= 0:
                stream.credit_event.clear()
                await stream.credit_event.wait()
            try:
                data = await self._read_coalesced(stream)
            except (ConnectionError, OSError):
                data = b""
            if not data:
                self._end(stream, frames.REASON_NORMAL)
                return
            stream.credit -= len(data)
            if self._out is not None:
                self._out.put_nowait(frames.pack(frames.DATA, stream.sid, data))

    async def _read_coalesced(self, stream: _Stream) -> bytes:
        limit = min(frames.MAX_PAYLOAD, stream.credit)
        data = await stream.reader.read(limit)
        while data and len(data) < min(COALESCE_BYTES, limit):
            try:
                more = await asyncio.wait_for(stream.reader.read(limit - len(data)), COALESCE_WAIT_SECONDS)
            except asyncio.TimeoutError:
                break
            if not more:
                break
            data += more
        return data

    async def _pre_auth_deadline(self, stream: _Stream) -> None:
        await self._sleep(PRE_AUTH_SECONDS)
        if not stream.info.request_seen:
            logger.info("phone_link_stream_idle_before_request", stream=stream.sid)
            self._end(stream, frames.REASON_IDLE)
