
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest
from starlette.websockets import WebSocketDisconnect

from relay.phonelink import frames
from relay.phonelink.tunnel import (
    FRAME_RATE_CLOSE_CODE, DeviceMeter, LinkLimits, LinkRegistry, SourceLimiter, Tunnel)
from tests.relay_link.support import Phone, client_hello, host_for, link_relay, ppv2, tunnel
from tests.relay_link.test_link_flow import SlowWriter, settle
from tests.relay_v2_support import Device, Issuer


@pytest.fixture
def issuer() -> Issuer:
    return Issuer()


@pytest.fixture
def device() -> Device:
    return Device()


def test_frames_reject_empty_data_and_a_trust_with_a_payload():
    with pytest.raises(frames.FrameError):
        frames.unpack(frames.pack(frames.DATA, 1, b""))
    with pytest.raises(frames.FrameError):
        frames.unpack(frames.pack(frames.TRUST, 1, b"x"))
    assert frames.unpack(frames.pack(frames.TRUST, 1)) == (frames.TRUST, 1, b"")


def _tunnel(limits: LinkLimits = LinkLimits()):
    sent = []

    async def send(raw: bytes) -> None:
        sent.append(frames.unpack(raw))

    principal = SimpleNamespace(claims=SimpleNamespace(sub="a" * 26))
    return Tunnel(principal, send, LinkRegistry(limits)), sent


def test_a_second_close_and_data_after_close_are_dropped_and_the_inbox_is_capped():
    async def scenario():
        tunnel_, _sent = _tunnel(LinkLimits(max_inbox_frames=3))
        writer = SlowWriter()
        task = asyncio.ensure_future(
            tunnel_.serve(asyncio.StreamReader(), writer, "1.2.3.4", 9, "h", b"hello"))
        await settle()
        stream = tunnel_.streams[1]
        tunnel_.on_frame(frames.CLOSE, 1, b"")
        tunnel_.on_frame(frames.CLOSE, 1, b"")
        tunnel_.on_frame(frames.DATA, 1, b"late")
        assert stream.inbox.qsize() == 1 and stream.outstanding == 0
        writer.release.set()
        await asyncio.wait_for(task, 2)

        task = asyncio.ensure_future(
            tunnel_.serve(asyncio.StreamReader(), SlowWriter(), "1.2.3.4", 9, "h", b"hello"))
        await settle()
        stream = tunnel_.streams[2]
        for _ in range(3):
            tunnel_.on_frame(frames.DATA, 2, b"x")
        await settle()
        assert stream.inbox.qsize() == 2 and 2 in tunnel_.streams
        tunnel_.on_frame(frames.DATA, 2, b"x")
        tunnel_.on_frame(frames.DATA, 2, b"x")
        await settle()
        assert 2 not in tunnel_.streams, "the queue cap ends the stream"
        await asyncio.wait_for(task, 2)

    asyncio.run(scenario())


def test_a_frame_flood_closes_the_tunnel_with_a_named_code(issuer, device):
    with link_relay(issuer, LinkLimits(frames_per_second=5)) as (client, _port), \
            tunnel(client, device, issuer) as mac:
        with pytest.raises(WebSocketDisconnect) as gone:
            for _ in range(200):
                mac.send(frames.WINDOW, 9, frames.window_payload(0))
            mac.frame()
        assert gone.value.code == FRAME_RATE_CLOSE_CODE


def test_text_frames_count_against_the_frame_rate(issuer, device):
    with link_relay(issuer, LinkLimits(frames_per_second=5)) as (client, _port), \
            tunnel(client, device, issuer) as mac:
        with pytest.raises(WebSocketDisconnect) as gone:
            for _ in range(200):
                mac.session.send_text("x")
            mac.frame()
        assert gone.value.code == FRAME_RATE_CLOSE_CODE


def test_connection_caps_refuse_at_accept(issuer, device):
    limits = LinkLimits(max_pre_hello=2, max_connections=3, max_streams_per_ip=100,
                        opens_per_ip_per_second=1000)
    with link_relay(issuer, limits) as (client, port), tunnel(client, device, issuer) as mac:
        registry = client.app.state.link
        held = [Phone(port), Phone(port)]
        deadline = time.monotonic() + 3
        while registry.pre_hello < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert Phone(port).is_closed(), "the third pre-hello connection is refused"
        held[0].send(client_hello(host_for(device)))
        assert mac.accept_stream()[0] == 1
        deadline = time.monotonic() + 3
        while registry.pre_hello != 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        third = Phone(port)
        deadline = time.monotonic() + 3
        while registry.connections < 3 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert Phone(port).is_closed(), "the total cap refuses too"
        assert registry.connections == 3
        third.close()
        held[1].close()


def test_the_open_rate_reserve_keeps_half_for_trusted_addresses():
    now = [0.0]
    meter = DeviceMeter(LinkLimits(opens_per_second=20, opens_burst=20), clock=lambda: now[0])
    meter.trust("198.51.100.1")
    strangers = sum(meter.allow_open(False) for _ in range(100))
    assert strangers == 10, "strangers together get at most half"
    assert sum(meter.allow_open(True) for _ in range(100)) == 10, "trusted keep the rest"


def _burst(limiter: SourceLimiter, ip: str, trusted: bool, count: int) -> int:
    let_in = 0
    for _ in range(count):
        if limiter.admit(ip) and limiter.allow(ip, trusted):
            let_in += 1
    return let_in


def test_a_trusted_address_opens_a_burst_of_30_and_an_untrusted_one_gets_12():
    now = [0.0]
    limiter = SourceLimiter(LinkLimits(max_streams_per_ip=100, trusted_streams_per_ip=100),
                            clock=lambda: now[0])
    assert _burst(limiter, "198.51.100.1", True, 30) == 30
    assert _burst(limiter, "203.0.113.1", False, 30) == 12, "a stranger's burst is 12, then limited"
    now[0] += 1.0
    assert _burst(limiter, "203.0.113.1", False, 30) == 5
    assert _burst(limiter, "198.51.100.1", True, 60) == 18 + 20, "the rest of 48, then 20 a second"


def test_the_per_address_concurrency_caps_hold():
    limiter = SourceLimiter(LinkLimits(ip_burst=1000, trusted_ip_burst=1000))
    assert _burst(limiter, "203.0.113.1", False, 20) == 8, "8 concurrent for an untrusted address"
    assert _burst(limiter, "198.51.100.1", True, 50) == 32, "32 concurrent for a trusted one"
    limiter.release("198.51.100.1")
    assert _burst(limiter, "198.51.100.1", True, 1) == 1, "a released slot is reusable"


def test_a_stranger_saturating_the_untrusted_bucket_leaves_a_trusted_address_room():
    now = [0.0]
    meter = DeviceMeter(LinkLimits(), clock=lambda: now[0])
    meter.trust("198.51.100.1")
    strangers = sum(meter.allow_open(False) for _ in range(200))
    assert strangers == 24, "strangers together get half of the 48 burst"
    assert sum(meter.allow_open(True) for _ in range(200)) == 24, "the trusted phone keeps the rest"


def test_trust_expires_and_is_capped_per_device():
    now = [0.0]
    limits = LinkLimits(max_trusted_ips=3, trust_seconds=100)
    meter = DeviceMeter(limits, clock=lambda: now[0])
    for i in range(5):
        meter.trust(f"198.51.100.{i}")
        now[0] += 1
    assert [meter.is_trusted(f"198.51.100.{i}") for i in range(5)] == [False, False, True, True, True]
    now[0] += 100
    assert not meter.is_trusted("198.51.100.4"), "a vouch lapses"


def test_strangers_saturating_their_half_cannot_block_a_trusted_address(issuer, device):
    limits = LinkLimits(max_streams=4, opens_per_second=1000, max_streams_per_ip=100,
                        opens_per_ip_per_second=1000)
    with link_relay(issuer, limits, link_proxy_protocol="required") as (client, port), \
            tunnel(client, device, issuer) as mac:
        hello = client_hello(host_for(device))
        meter = client.app.state.link.meter(device.device_id)
        keep = [Phone(port).send(ppv2("203.0.113.1", 1) + hello)]
        sid, opened, _ = mac.accept_stream()
        assert opened["client_ip"] == "203.0.113.1"
        mac.send(frames.TRUST, sid)
        deadline = time.monotonic() + 3
        while not meter.is_trusted("203.0.113.1") and time.monotonic() < deadline:
            time.sleep(0.01)
        assert meter.is_trusted("203.0.113.1")
        for n in (2, 3):
            keep.append(Phone(port).send(ppv2(f"203.0.113.{n}", 1) + hello))
            mac.accept_stream()
        assert Phone(port).send(ppv2("203.0.113.9", 1) + hello).is_closed(), "a third stranger is out"
        keep.append(Phone(port).send(ppv2("203.0.113.1", 2) + hello))
        assert mac.accept_stream()[1]["client_ip"] == "203.0.113.1"
        assert Phone(port).send(ppv2("203.0.113.1", 3) + hello).is_closed(), "the device total holds"
        assert keep


def test_replay_cache_keys_and_budgets_include_the_audience():
    from relay.auth import LINK_TUNNEL_POP_AUDIENCE, POP_AUDIENCE, ReplayCache
    cache = ReplayCache(max_per_device=2)
    assert cache.claim("j", 1, "dev", POP_AUDIENCE) is None
    assert cache.claim("j", 1, "dev", LINK_TUNNEL_POP_AUDIENCE) is None, "same jti and ts, other audience"
    assert cache.claim("j", 1, "dev", POP_AUDIENCE) == "pop_replayed"
    assert cache.claim("k", 2, "dev", LINK_TUNNEL_POP_AUDIENCE) is None
    assert cache.claim("l", 3, "dev", LINK_TUNNEL_POP_AUDIENCE) == "pop_device_limit"
    assert cache.claim("m", 4, "dev", POP_AUDIENCE) is None, "the share publisher is not starved"


def test_the_link_breaker_has_its_own_event_and_metric_names():
    from relay.egress import EgressBreaker, metrics_record
    from structlog.testing import capture_logs
    link = LinkRegistry(LinkLimits(link_daily_bytes=10)).egress
    with capture_logs() as logs:
        assert link.record(11) is True
    assert [e["event"] for e in logs] == ["relay_link_breaker_tripped"]
    record = metrics_record(link)
    assert record["link_bytes_out"] == 11 and record["link_breaker_tripped"] == 1
    assert "bytes_out" not in record
    names = [m["Name"] for m in record["_aws"]["CloudWatchMetrics"][0]["Metrics"]]
    assert names == ["link_bytes_out", "link_breaker_tripped"]
    assert metrics_record(EgressBreaker(10))["bytes_out"] == 0, "the share breaker is unchanged"


def test_refusals_are_aggregated_not_logged_one_by_one():
    from structlog.testing import capture_logs
    registry = LinkRegistry()
    with capture_logs() as logs:
        for _ in range(1000):
            registry.refuse("unknown_or_offline")
        registry._refused_flush -= 60
        registry.refuse("streams")
    assert len(logs) == 1 and logs[0]["unknown_or_offline"] == 1000 and logs[0]["streams"] == 1
