
from __future__ import annotations

import asyncio
import json
import os
import socket
import time
from collections import deque
from typing import Awaitable, Callable, Optional

import structlog

from src.core.computers.mux import frames as f

log = structlog.get_logger(__name__)

STREAM_WINDOW = 256 * 1024
GRANT_BATCH = 64 * 1024
MAX_STREAMS = 128
MAX_BUFFERED = 8 * 1024 * 1024
PING_INTERVAL = 10.0
IDLE_TIMEOUT = 30.0
MAX_CONTROL_QUEUE = 1024
WRITE_STALL_TIMEOUT = 30.0
ALLOWED_SERVICES = frozenset({"peer-api"})
_MAX_ID = 0xFFFFFFFF


class MuxError(Exception):
    pass


class StreamReset(MuxError):

    def __init__(self, reason: int) -> None:
        super().__init__(f"stream reset ({reason})")
        self.reason = reason


class MuxStream:

    def __init__(self, session: "MuxSession", sid: int, service: str) -> None:
        self.session, self.id, self.service = session, sid, service
        self._inbuf = bytearray()
        self._recv_left = STREAM_WINDOW
        self._ack_owed = 0
        self._send_credit = STREAM_WINDOW
        self._out: deque = deque()
        self._queued = False
        self._remote_fin = False
        self._fin_queued = False
        self._fin_sent = False
        self.reset_reason: Optional[int] = None
        self._event = asyncio.Event()

    async def read(self, n: int = 65536) -> bytes:
        self._grant_owed()
        while True:
            if self._inbuf:
                chunk = bytes(self._inbuf[:n])
                del self._inbuf[:len(chunk)]
                self._ack_owed += len(chunk)
                return chunk
            if self.reset_reason is not None:
                raise StreamReset(self.reset_reason)
            if self._remote_fin:
                return b""
            self._event.clear()
            await self._event.wait()

    def _grant_owed(self) -> None:
        if self._ack_owed and self.reset_reason is None and (
                self._ack_owed >= GRANT_BATCH or self._recv_left < STREAM_WINDOW // 2):
            grant, self._ack_owed = self._ack_owed, 0
            self._recv_left += grant
            self.session._control(f.WINDOW, self.id, f.pack_u32(grant))

    async def write(self, data: bytes) -> None:
        view = memoryview(data)
        while len(view):
            if self.reset_reason is not None:
                raise StreamReset(self.reset_reason)
            if self._fin_queued:
                raise MuxError("write after close")
            s = self.session
            n = min(len(view), self._send_credit, f.MAX_PAYLOAD, MAX_BUFFERED - s._buffered)
            if n <= 0:
                self._event.clear()
                s._space.clear()
                if self._send_credit <= 0:
                    await self._event.wait()
                else:
                    await s._space.wait()
                continue
            self._send_credit -= n
            s._buffered += n
            self._out.append(bytes(view[:n]))
            view = view[n:]
            s._schedule(self)

    def close(self) -> None:
        if self._fin_queued or self.reset_reason is not None:
            return
        self._fin_queued = True
        self._out.append(None)
        self.session._schedule(self)

    def reset(self, reason: int = f.RST_ERROR) -> None:
        if self.reset_reason is None:
            self.session._control(f.RST, self.id, f.pack_u8(reason))
            self._die(reason)

    @property
    def finished(self) -> bool:
        return self.reset_reason is not None or (self._remote_fin and self._fin_sent)

    def _die(self, reason: int) -> None:
        self.reset_reason = reason
        for item in self._out:
            if item:
                self.session._buffered -= len(item)
        self._out.clear()
        self.session._forget(self)
        self._event.set()
        self.session._space.set()


class MuxSession:

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, *, dialer: bool,
                 on_open: Optional[Callable[[MuxStream], Awaitable[None]]] = None,
                 services: frozenset = ALLOWED_SERVICES, ping_interval: float = PING_INTERVAL,
                 idle_timeout: float = IDLE_TIMEOUT) -> None:
        self._r, self._w, self.dialer = reader, writer, dialer
        self._on_open, self._services = on_open, services
        self._ping_interval, self._idle_timeout = ping_interval, idle_timeout
        self._streams: dict[int, MuxStream] = {}
        self._next_id = 1 if dialer else 2
        self._peer_high = 0 if dialer else -1
        self._ctl: deque = deque()
        self._overflowed = False
        self.read_error: Optional[BaseException] = None
        self._ready: deque = deque()
        self._buffered = 0
        self._wake = asyncio.Event()
        self._space = asyncio.Event()
        self._tasks: list = []
        self._handlers: set = set()
        self._hello: asyncio.Future = asyncio.get_running_loop().create_future()
        self._got_hello = False
        self._last_rx = time.monotonic()
        self.closed = asyncio.Event()
        self.close_reason: Optional[str] = None
        self.goaway_reason: Optional[int] = None

    async def start(self, hello: dict) -> None:
        body = json.dumps(hello, separators=(",", ":")).encode()
        if len(body) > f.MAX_HELLO:
            raise MuxError("hello too large")
        _tune_socket(self._w)
        self._ctl.append(f.pack(f.HELLO, 0, body))
        self._last_rx = time.monotonic()
        loop = asyncio.get_running_loop()
        self._tasks = [loop.create_task(self._read_loop()), loop.create_task(self._write_loop()),
                       loop.create_task(self._keepalive())]

    async def hello(self) -> dict:
        return await asyncio.shield(self._hello)

    async def open(self, service: str = "peer-api") -> MuxStream:
        if self.closed.is_set():
            raise MuxError("session closed")
        if len(self._streams) >= MAX_STREAMS:
            raise MuxError("stream limit")
        if self._next_id > _MAX_ID:
            raise MuxError("stream ids exhausted")
        s = MuxStream(self, self._next_id, service)
        self._next_id += 2
        self._streams[s.id] = s
        self._control(f.OPEN, s.id, service.encode("ascii"))
        return s

    async def close(self, reason: int = f.GO_NORMAL) -> None:
        if not self.closed.is_set():
            self._ctl.append(f.pack(f.GOAWAY, 0, f.pack_u8(reason)))
            self._wake.set()
            await self._flush_control()
        self._teardown("closed locally")
        await self.closed.wait()

    async def wait_closed(self) -> None:
        """Block until the session is gone."""
        await self.closed.wait()

    def _control(self, ftype: int, sid: int, payload: bytes = b"") -> None:
        if len(self._ctl) >= MAX_CONTROL_QUEUE:
            if not self._overflowed:
                self._overflowed = True
                self._fail(f.GO_PROTOCOL, "control backlog")
            return
        if not self.closed.is_set():
            self._ctl.append(f.pack(ftype, sid, payload))
            self._wake.set()

    def _schedule(self, s: MuxStream) -> None:
        if not s._queued and s._out:
            s._queued = True
            self._ready.append(s)
        self._wake.set()

    def _forget(self, s: MuxStream) -> None:
        self._streams.pop(s.id, None)

    async def _flush_control(self) -> None:
        try:
            while self._ctl:
                self._w.write(self._ctl.popleft())
            await asyncio.wait_for(self._w.drain(), 1.0)
        except (ConnectionError, OSError, asyncio.TimeoutError):
            pass

    def _fail(self, reason: int, why: str) -> None:
        log.warning("mux_violation", why=why, reason=reason)
        asyncio.get_running_loop().create_task(self._fail_async(reason, why))

    async def _fail_async(self, reason: int, why: str) -> None:
        if not self.closed.is_set():
            self._ctl.clear()
            self._ctl.append(f.pack(f.GOAWAY, 0, f.pack_u8(reason)))
            await self._flush_control()
            self._teardown(why)

    def _teardown(self, why: str) -> None:
        if self.closed.is_set():
            return
        self.close_reason = why
        self.closed.set()
        for s in list(self._streams.values()):
            s._die(f.RST_ERROR)
        for t in self._tasks + list(self._handlers):
            if t is not asyncio.current_task():
                t.cancel()
        try:
            self._w.close()
        except OSError:
            pass
        if not self._hello.done():
            self._hello.set_exception(MuxError(why))
            self._hello.exception()
        self._space.set()

    async def _write_loop(self) -> None:
        try:
            while True:
                if self._ctl:
                    while self._ctl:
                        self._w.write(self._ctl.popleft())
                elif self._ready:
                    s = self._ready.popleft()
                    s._queued = False
                    if not s._out:
                        continue
                    item = s._out.popleft()
                    if item is None:
                        s._fin_sent = True
                        self._w.write(f.pack(f.FIN, s.id))
                        if s.finished:
                            self._forget(s)
                    else:
                        while s._out and s._out[0] is not None and len(item) + len(s._out[0]) <= f.MAX_PAYLOAD:
                            item += s._out.popleft()
                        self._w.write(f.pack(f.DATA, s.id, item))
                        self._buffered -= len(item)
                        self._space.set()
                    if s._out:
                        s._queued = True
                        self._ready.append(s)
                else:
                    self._wake.clear()
                    if not (self._ctl or self._ready):
                        await self._wake.wait()
                    continue
                await asyncio.wait_for(self._w.drain(), WRITE_STALL_TIMEOUT)
        except (ConnectionError, OSError) as exc:
            self._teardown(f"write failed: {type(exc).__name__}")
        except asyncio.CancelledError:
            raise

    async def _read_loop(self) -> None:
        try:
            while True:
                frame = await f.read_frame(self._r)
                self._last_rx = time.monotonic()
                if not self._dispatch(frame):
                    return
        except f.FrameError as exc:
            self._fail(f.GO_PROTOCOL, str(exc))
        except (asyncio.IncompleteReadError, ConnectionError, OSError) as exc:
            self.read_error = exc
            self._teardown("connection lost")
        except asyncio.CancelledError:
            raise

    async def _keepalive(self) -> None:
        """PING on an interval; close when nothing at all arrived within the idle timeout."""
        while True:
            await asyncio.sleep(self._ping_interval)
            if time.monotonic() - self._last_rx > self._idle_timeout:
                self._teardown("idle timeout")
                return
            self._control(f.PING, 0, os.urandom(8))

    def _dispatch(self, fr: f.Frame) -> bool:
        t = fr.type
        if t == f.HELLO:
            return self._on_hello(fr)
        if t == f.GOAWAY:
            self.goaway_reason = fr.payload[0]
            self._teardown(f"goaway {fr.payload[0]}")
            return False
        if not self._got_hello:
            self._fail(f.GO_PROTOCOL, "frame before hello")
            return False
        if t == f.PING:
            self._control(f.PONG, 0, fr.payload)
        elif t == f.PONG:
            pass
        elif t == f.OPEN:
            return self._on_open_frame(fr)
        else:
            return self._on_stream_frame(fr)
        return True

    def _on_hello(self, fr: f.Frame) -> bool:
        if self._got_hello:
            self._fail(f.GO_PROTOCOL, "second hello")
            return False
        try:
            obj = json.loads(fr.payload)
            if not isinstance(obj, dict):
                raise ValueError("not an object")
        except ValueError:
            self._fail(f.GO_PROTOCOL, "hello is not a json object")
            return False
        if obj.get("v") != f.PROTOCOL_VERSION:
            self._fail(f.GO_VERSION, "version mismatch")
            return False
        self._got_hello = True
        if not self._hello.done():
            self._hello.set_result(obj)
        return True

    def _on_open_frame(self, fr: f.Frame) -> bool:
        sid = fr.stream
        peer_parity = 0 if self.dialer else 1
        if sid % 2 != peer_parity or sid <= self._peer_high:
            self._fail(f.GO_PROTOCOL, "bad stream id on open")
            return False
        self._peer_high = sid
        try:
            service = fr.payload.decode("ascii")
        except UnicodeDecodeError:
            service = ""
        if service not in self._services or self._on_open is None:
            self._control(f.RST, sid, f.pack_u8(f.RST_UNKNOWN))
            return True
        if len(self._streams) >= MAX_STREAMS:
            self._control(f.RST, sid, f.pack_u8(f.RST_LIMIT))
            return True
        s = MuxStream(self, sid, service)
        self._streams[sid] = s
        task = asyncio.get_running_loop().create_task(self._run_handler(s))
        self._handlers.add(task)
        task.add_done_callback(self._handlers.discard)
        return True

    async def _run_handler(self, s: MuxStream) -> None:
        try:
            await self._on_open(s)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("mux_open_handler_failed", error=type(exc).__name__)
            s.reset(f.RST_UNAVAILABLE)

    def _known_closed(self, sid: int) -> bool:
        if sid % 2 == (1 if self.dialer else 0):
            return sid < self._next_id
        return sid <= self._peer_high

    def _on_stream_frame(self, fr: f.Frame) -> bool:
        s = self._streams.get(fr.stream)
        if s is None:
            if self._known_closed(fr.stream):
                return True
            self._fail(f.GO_PROTOCOL, "frame for a stream that was never opened")
            return False
        if fr.type == f.DATA:
            n = len(fr.payload)
            if n > s._recv_left:
                self._fail(f.GO_PROTOCOL, "data beyond credit")
                return False
            s._recv_left -= n
            s._inbuf += fr.payload
        elif fr.type == f.FIN:
            s._remote_fin = True
            if s.finished:
                self._forget(s)
        elif fr.type == f.RST:
            s._die(fr.payload[0])
        elif fr.type == f.WINDOW:
            s._send_credit += int.from_bytes(fr.payload, "big")
            if s._send_credit > STREAM_WINDOW:
                self._fail(f.GO_PROTOCOL, "credit above the window")
                return False
        s._event.set()
        return True


def _tune_socket(writer: asyncio.StreamWriter) -> None:
    sock = writer.get_extra_info("socket")
    if sock is None:
        return
    for level, opt in ((socket.IPPROTO_TCP, socket.TCP_NODELAY), (socket.SOL_SOCKET, socket.SO_KEEPALIVE)):
        try:
            sock.setsockopt(level, opt, 1)
        except OSError:
            pass


async def bridge(stream: MuxStream, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:

    async def down() -> None:
        while True:
            chunk = await stream.read()
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
        if writer.can_write_eof():
            writer.write_eof()

    async def up() -> None:
        while True:
            chunk = await reader.read(f.MAX_PAYLOAD)
            if not chunk:
                break
            await stream.write(chunk)
        stream.close()

    try:
        await asyncio.gather(down(), up())
    except (StreamReset, ConnectionError, OSError):
        stream.reset(f.RST_ERROR)
    finally:
        writer.close()
