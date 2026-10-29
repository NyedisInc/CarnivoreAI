
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from relay.phonelink import frames
from relay.phonelink.tunnel import DeviceMeter, LinkLimits, LinkRegistry, Tunnel
from tests.relay_link.support import Phone, client_hello, host_for, link_relay, tunnel
from tests.relay_support import data_frame, watch_protocols
from tests.relay_v2_support import Device, Issuer
from tests.test_relay_sockets import PUBLISH_TOKEN, SHARE_TOKEN, publisher, wait_for_links
from tests.relay_support import links_frame

CHUNK = frames.MAX_PAYLOAD
WINDOW = frames.INITIAL_WINDOW


class SlowWriter:

    def __init__(self) -> None:
        self.written = []
        self.release = asyncio.Event()
        self.transport = None

    def write(self, data: bytes) -> None:
        self.written.append(data)

    async def drain(self) -> None:
        await self.release.wait()

    def close(self) -> None:
        pass


class EndlessReader:

    def __init__(self) -> None:
        self.asked = []

    async def read(self, count: int) -> bytes:
        self.asked.append(count)
        await asyncio.sleep(0)
        return b"u" * count


def make_tunnel():
    sent = []

    async def send(raw: bytes) -> None:
        sent.append(frames.unpack(raw))

    principal = SimpleNamespace(claims=SimpleNamespace(sub="a" * 26))
    return Tunnel(principal, send, LinkRegistry()), sent


async def settle() -> None:
    for _ in range(20):
        await asyncio.sleep(0)


def test_a_slow_phone_never_buffers_past_one_window_and_credit_returns_only_after_writes():
    async def scenario():
        tunnel_, sent = make_tunnel()
        writer = SlowWriter()
        reader = asyncio.StreamReader()
        task = asyncio.ensure_future(tunnel_.serve(reader, writer, "1.2.3.4", 9, "h", b"hello"))
        await settle()
        stream = tunnel_.streams[1]
        for _ in range(WINDOW // CHUNK):
            tunnel_.on_frame(frames.DATA, 1, b"d" * CHUNK)
        await settle()
        assert stream.outstanding == WINDOW
        assert len(writer.written) == 1
        assert not [f for f in sent if f[0] == frames.WINDOW]
        tunnel_.on_frame(frames.DATA, 1, b"x")
        await settle()
        assert sent[-1] == (frames.CLOSE, 1, bytes([frames.REASON_ERROR]))
        await asyncio.wait_for(task, 2)
        assert 1 not in tunnel_.streams

    asyncio.run(scenario())


def test_credit_is_granted_back_only_after_each_write_completes():
    async def scenario():
        tunnel_, sent = make_tunnel()
        writer = SlowWriter()
        task = asyncio.ensure_future(
            tunnel_.serve(asyncio.StreamReader(), writer, "1.2.3.4", 9, "h", b"hello"))
        await settle()
        tunnel_.on_frame(frames.DATA, 1, b"a" * 100)
        tunnel_.on_frame(frames.DATA, 1, b"b" * 50)
        await settle()
        assert not [f for f in sent if f[0] == frames.WINDOW]
        writer.release.set()
        await settle()
        credits = [frames.window_credit(f[2]) for f in sent if f[0] == frames.WINDOW]
        assert credits == [100, 50]
        assert tunnel_.streams[1].outstanding == 0
        tunnel_.close_all(frames.REASON_ERROR)
        await asyncio.wait_for(task, 2)

    asyncio.run(scenario())


def test_the_relay_never_sends_past_the_macs_credit():
    async def scenario():
        tunnel_, sent = make_tunnel()
        reader = EndlessReader()
        task = asyncio.ensure_future(tunnel_.serve(reader, SlowWriter(), "1.2.3.4", 9, "h", b"hello"))
        await settle()
        stream = tunnel_.streams[1]
        data = [f for f in sent if f[0] == frames.DATA]
        assert sum(len(f[2]) for f in data) == WINDOW
        assert stream.send_credit == 0 and max(reader.asked) <= CHUNK
        before = len(sent)
        await settle()
        assert len(sent) == before
        tunnel_.on_frame(frames.WINDOW, 1, frames.window_payload(1000))
        await settle()
        more = [f for f in sent[before:] if f[0] == frames.DATA]
        assert sum(len(f[2]) for f in more) == 1000
        tunnel_.on_frame(frames.WINDOW, 1, frames.window_payload(WINDOW + 1))
        await settle()
        assert sent[-1] == (frames.CLOSE, 1, bytes([frames.REASON_ERROR]))
        await asyncio.wait_for(task, 2)

    asyncio.run(scenario())


def test_the_device_meter_makes_a_burst_wait_at_the_sustained_rate():
    async def scenario():
        slept = []

        async def sleep(seconds: float) -> None:
            slept.append(seconds)

        meter = DeviceMeter(LinkLimits(device_bps=10, device_burst=100), clock=lambda: 0.0,
                            sleep=sleep)
        await meter.take(100)
        assert slept == []
        await meter.take(50)
        assert slept == [5.0]

    asyncio.run(scenario())




@pytest.fixture
def issuer() -> Issuer:
    return Issuer()


@pytest.fixture
def device() -> Device:
    return Device()


def test_link_breaker_trip_closes_link_streams_refuses_new_ones_and_spares_share_watchers(
        issuer, device):
    limits = LinkLimits(link_daily_bytes=10)
    with link_relay(issuer, limits) as (client, port), tunnel(client, device, issuer) as mac:
        with publisher(client, PUBLISH_TOKEN) as pub:
            pub.send_text(json.dumps(links_frame({"l1": SHARE_TOKEN})))
            wait_for_links(client, 1)
            with client.websocket_connect("/watch/l1", subprotocols=watch_protocols(SHARE_TOKEN)) as watcher:
                phone = Phone(port).send(client_hello(host_for(device)))
                sid, _, _ = mac.accept_stream()
                mac.send(frames.DATA, sid, b"z" * 100)
                assert phone.recv_exact(100) == b"z" * 100
                seen = []
                while not any(f[0] == frames.CLOSE for f in seen):
                    seen.append(mac.frame())
                assert seen[-1] == (frames.CLOSE, sid, bytes([frames.REASON_BREAKER]))
                assert phone.is_closed()
                assert Phone(port).send(client_hello(host_for(device))).is_closed()
                pub.send_text(json.dumps(data_frame("l1", "still watching")))
                assert watcher.receive_bytes().decode() == "still watching"
        state = client.app.state
        assert state.egress.day_bytes == len("still watching") and not state.egress.tripped()
        assert state.link.egress.tripped() is True
        assert device.ten not in state.tenancy._tenants


def test_share_watchers_do_not_move_the_links_breaker(issuer, device):
    with link_relay(issuer) as (client, _port):
        with publisher(client, PUBLISH_TOKEN) as pub:
            pub.send_text(json.dumps(links_frame({"l1": SHARE_TOKEN})))
            wait_for_links(client, 1)
            with client.websocket_connect("/watch/l1", subprotocols=watch_protocols(SHARE_TOKEN)) as w:
                pub.send_text(json.dumps(data_frame("l1", "x" * 500)))
                w.receive_bytes()
        assert client.app.state.egress.day_bytes >= 500
        assert client.app.state.link.egress.day_bytes == 0


def test_device_daily_cap_closes_streams_and_refuses_new_ones(issuer, device):
    with link_relay(issuer, LinkLimits(device_day_bytes=10)) as (client, port), \
            tunnel(client, device, issuer) as mac:
        phone = Phone(port).send(client_hello(host_for(device)))
        sid, _, _ = mac.accept_stream()
        mac.send(frames.DATA, sid, b"z" * 100)
        assert mac.frame() == (frames.CLOSE, sid, bytes([frames.REASON_LIMIT]))
        assert phone.is_closed()
        assert Phone(port).send(client_hello(host_for(device))).is_closed()
