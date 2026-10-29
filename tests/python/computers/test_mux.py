
from __future__ import annotations

import asyncio
import socket

import pytest

from src.core.computers.mux import frames as f
from src.core.computers.mux.session import (MAX_STREAMS, STREAM_WINDOW, MuxError, MuxSession, StreamReset,
                                            bridge)


async def _pair(on_open=None, **kw):
    a, b = socket.socketpair()
    ra, wa = await asyncio.open_connection(sock=a)
    rb, wb = await asyncio.open_connection(sock=b)
    d = MuxSession(ra, wa, dialer=True, **kw)
    m = MuxSession(rb, wb, dialer=False, on_open=on_open, **kw)
    await d.start({"v": 1, "proto": 1})
    await m.start({"v": 1, "back_path": "x"})
    await d.hello(), await m.hello()
    return d, m


async def _echo(stream):
    while True:
        data = await stream.read()
        if not data:
            break
        await stream.write(data)
    stream.close()


async def _hold(stream):
    await asyncio.sleep(30)


async def _raw_acceptor(on_open=_echo):
    a, b = socket.socketpair()
    ra, wa = await asyncio.open_connection(sock=a)
    rb, wb = await asyncio.open_connection(sock=b)
    m = MuxSession(rb, wb, dialer=False, on_open=on_open)
    await m.start({"v": 1})
    return m, ra, wa


async def _frames_until_eof(reader):
    out = []
    while True:
        try:
            out.append(await asyncio.wait_for(f.read_frame(reader), 2))
        except (asyncio.IncompleteReadError, asyncio.TimeoutError):
            return out


@pytest.mark.asyncio
async def test_concurrent_streams_echo():
    d, m = await _pair(on_open=_echo)

    async def one(i):
        s = await d.open()
        payload = bytes([i]) * (50_000 + i)
        writer = asyncio.create_task(s.write(payload))
        out = bytearray()
        while len(out) < len(payload):
            out += await s.read()
        await writer
        s.close()
        return bytes(out) == payload

    assert all(await asyncio.gather(*(one(i) for i in range(20))))
    await d.close()
    await m.wait_closed()


@pytest.mark.asyncio
async def test_credit_stalls_and_resumes():
    held = []

    async def hold(stream):
        held.append(stream)
        await asyncio.sleep(30)

    d, m = await _pair(on_open=hold)
    s = await d.open()
    big = b"z" * (STREAM_WINDOW + 100_000)
    w = asyncio.create_task(s.write(big))
    await asyncio.sleep(0.3)
    assert not w.done(), "writer must stall at the window"
    assert held and len(held[0]._inbuf) == STREAM_WINDOW
    got = bytearray()
    while len(got) < len(big):
        got += await held[0].read(65536)
    await asyncio.wait_for(w, 5)
    assert bytes(got) == big
    await d.close()


@pytest.mark.asyncio
async def test_unknown_service_is_reset_without_side_effect():
    called = []

    async def on_open(s):
        called.append(s)

    d, m = await _pair(on_open=on_open)
    s = await d.open("shell")
    with pytest.raises(StreamReset) as e:
        await asyncio.wait_for(s.read(), 3)
    assert e.value.reason == f.RST_UNKNOWN
    assert not called and not d.closed.is_set() and not m.closed.is_set()
    await d.close()


@pytest.mark.asyncio
async def test_oversize_frame_kills_connection_before_reading_payload():
    m, ra, wa = await _raw_acceptor()
    wa.write(f.pack(f.HELLO, 0, b'{"v":1}'))
    wa.write(f.HEADER.pack(f.DATA, 1, f.MAX_PAYLOAD + 1))
    await wa.drain()
    await asyncio.wait_for(m.wait_closed(), 3)
    assert m.close_reason == "frame over the length cap"
    seen = await _frames_until_eof(ra)
    assert any(x.type == f.GOAWAY and x.payload == bytes([f.GO_PROTOCOL]) for x in seen)


@pytest.mark.asyncio
@pytest.mark.parametrize("wire,why", [
    (f.pack(f.OPEN, 2, b"peer-api"), "bad stream id on open"),
    (f.pack(f.DATA, 7, b"x"), "frame for a stream that was never opened"),
    (f.pack(f.PING, 0, b"short"), "ping payload must be 8 bytes"),
    (f.HEADER.pack(99, 0, 0), "unknown frame type"),
])
async def test_violations_end_with_goaway_protocol(wire, why):
    m, ra, wa = await _raw_acceptor()
    wa.write(f.pack(f.HELLO, 0, b'{"v":1}') + wire)
    await wa.drain()
    await asyncio.wait_for(m.wait_closed(), 3)
    assert m.close_reason == why
    seen = await _frames_until_eof(ra)
    assert any(x.type == f.GOAWAY and x.payload == bytes([f.GO_PROTOCOL]) for x in seen)


@pytest.mark.asyncio
async def test_data_beyond_credit_and_version_mismatch():
    m, ra, wa = await _raw_acceptor(_hold)
    wa.write(f.pack(f.HELLO, 0, b'{"v":1}') + f.pack(f.OPEN, 1, b"peer-api"))
    for _ in range(STREAM_WINDOW // f.MAX_PAYLOAD + 1):
        wa.write(f.pack(f.DATA, 1, b"y" * f.MAX_PAYLOAD))
    await wa.drain()
    await asyncio.wait_for(m.wait_closed(), 3)
    assert m.close_reason == "data beyond credit"

    m2, ra2, wa2 = await _raw_acceptor()
    wa2.write(f.pack(f.HELLO, 0, b'{"v":2}'))
    await wa2.drain()
    await asyncio.wait_for(m2.wait_closed(), 3)
    assert m2.close_reason == "version mismatch"
    seen = await _frames_until_eof(ra2)
    assert [x.type for x in seen] == [f.HELLO, f.GOAWAY] and seen[1].payload == bytes([f.GO_VERSION])
    with pytest.raises(MuxError):
        await m2.hello()


@pytest.mark.asyncio
async def test_stream_cap():
    async def hold(s):
        await asyncio.sleep(30)

    d, m = await _pair(on_open=hold)
    for _ in range(MAX_STREAMS):
        await d.open()
    with pytest.raises(MuxError):
        await d.open()
    await d.close()


@pytest.mark.asyncio
async def test_ping_timeout_closes_silent_peer():
    a, b = socket.socketpair()
    ra, wa = await asyncio.open_connection(sock=a)
    s = MuxSession(ra, wa, dialer=True, ping_interval=0.05, idle_timeout=0.25)
    await s.start({"v": 1})
    await asyncio.wait_for(s.wait_closed(), 2)
    assert s.close_reason == "idle timeout"
    b.close()


@pytest.mark.asyncio
async def test_ping_keeps_a_quiet_link_alive():
    d, m = await _pair(ping_interval=0.05, idle_timeout=0.3)
    await asyncio.sleep(0.8)
    assert not d.closed.is_set() and not m.closed.is_set()
    await d.close()


@pytest.mark.asyncio
async def test_bridge_to_local_socket_and_goaway_resets_streams():
    async def local_echo(r, w):
        w.write(await r.read(100))
        await w.drain()
        w.close()

    srv = await asyncio.start_server(local_echo, "127.0.0.1", 0)
    port = srv.sockets[0].getsockname()[1]

    async def on_open(stream):
        r, w = await asyncio.open_connection("127.0.0.1", port)
        await bridge(stream, r, w)

    d, m = await _pair(on_open=on_open)
    s = await d.open()
    await s.write(b"hello")
    assert await asyncio.wait_for(s.read(), 3) == b"hello"
    s2 = await d.open()
    await m.close(f.GO_REMOVED)
    with pytest.raises(StreamReset):
        await asyncio.wait_for(s2.read(), 3)
    await asyncio.wait_for(d.wait_closed(), 3)
    assert d.goaway_reason == f.GO_REMOVED
    srv.close()
