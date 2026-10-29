
from __future__ import annotations

import calendar
import json

import pytest
from starlette.websockets import WebSocketDisconnect
from structlog.testing import capture_logs

from relay.bounded import OVERFLOW_CLOSE_CODE, REFUSED_CLOSE_CODE
from relay.config import DEFAULT_DAILY_EGRESS_BYTES, settings_from_env
from relay.egress import METRIC_NAMESPACE, EgressBreaker, metrics_record
from relay.tenancy import DEFAULT_LIMITS, OVER_CAP_CLOSE_CODE, QUOTA_CLOSE_CODE, Tenancy
from tests.relay_support import data_frame, links_frame, watch_protocols
from tests.relay_v2_support import DEFAULT_LIM, V2_TOKEN, Device, Issuer, SealedLink, links_v2
from tests.test_relay_sockets import (
    SHARE_TOKEN,
    build_settings,
    publisher,
    relay,
    wait_for_links,
)
from tests.test_relay_v2_sockets import closed_with, connect, v2_relay

BEFORE_MIDNIGHT = calendar.timegm((2026, 9, 23, 23, 59, 0))
AFTER_MIDNIGHT = BEFORE_MIDNIGHT + 60


class Clock:

    def __init__(self, now: float = 0.0) -> None:
        self.now = now
        self.slept: list = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds




@pytest.mark.asyncio
async def test_the_bucket_throttles_then_closes_on_sustained_excess():
    clock = Clock()
    tenancy = Tenancy(clock=clock, wall=lambda: BEFORE_MIDNIGHT, sleep=clock.sleep)
    lim = {**DEFAULT_LIM, "bps": 1000, "burst": 1000}
    outcome = None
    frames = 0
    while outcome is None and frames < 1000:
        outcome = await tenancy.consume("t", 1000, lim)
        frames += 1
    assert clock.slept, "the bucket throttled before it closed"
    assert outcome == (OVER_CAP_CLOSE_CODE, "rate_cap")
    assert clock.now >= 60, "closed only after a sustained minute"


@pytest.mark.asyncio
async def test_a_reconnect_after_a_rate_cap_close_gets_a_fresh_throttle_window():
    clock = Clock()
    tenancy = Tenancy(clock=clock, wall=lambda: BEFORE_MIDNIGHT, sleep=clock.sleep)
    lim = {**DEFAULT_LIM, "bps": 1000, "burst": 1000}
    outcome = None
    while outcome is None:
        outcome = await tenancy.consume("t", 1000, lim)
    assert outcome == (OVER_CAP_CLOSE_CODE, "rate_cap")
    closed_at = clock.now
    assert await tenancy.consume("t", 3000, lim) is None
    outcome = None
    while outcome is None:
        outcome = await tenancy.consume("t", 1000, lim)
    assert clock.now - closed_at >= 60, "the reconnect got its own sustained minute"


@pytest.mark.asyncio
async def test_a_burst_that_pauses_is_throttled_and_never_closed():
    clock = Clock()
    tenancy = Tenancy(clock=clock, wall=lambda: BEFORE_MIDNIGHT, sleep=clock.sleep)
    lim = {**DEFAULT_LIM, "bps": 1000, "burst": 1000}
    for _ in range(20):
        for _ in range(30):
            assert await tenancy.consume("t", 1000, lim) is None
        clock.now += 5
    assert clock.slept


@pytest.mark.asyncio
async def test_the_daily_quota_rolls_over_at_utc_midnight():
    wall = [BEFORE_MIDNIGHT]
    tenancy = Tenancy(clock=lambda: 0.0, wall=lambda: wall[0])
    lim = {**DEFAULT_LIM, "bytes_day": 100}
    assert await tenancy.consume("t", 100, lim) is None
    assert await tenancy.consume("t", 1, lim) == (QUOTA_CLOSE_CODE, "quota")
    assert tenancy.quota_spent("t", lim)
    wall[0] = AFTER_MIDNIGHT
    assert not tenancy.quota_spent("t", lim), "a new UTC day is a new budget"
    assert await tenancy.consume("t", 50, lim) is None


def test_limits_from_a_reauth_apply_to_the_next_frame():
    issuer, device = Issuer(), Device()
    link_id, nonce = device.link()
    with v2_relay(issuer) as (client, _factory):
        with connect(client, device, issuer.token(device)) as pub:
            pub.send_text(json.dumps(links_v2({link_id: V2_TOKEN}, {link_id: nonce})))
            tight = issuer.token(device, lim={**DEFAULT_LIM, "bytes_day": 8})
            pub.send_text(json.dumps(device.reauth(tight)))
            pub.send_bytes(SealedLink(link_id).open())
            assert closed_with(pub) == QUOTA_CLOSE_CODE


def test_the_v1_default_limits_are_the_contracts():
    assert DEFAULT_LIMITS == DEFAULT_LIM


def test_a_v1_publisher_gets_the_default_connection_cap():
    with relay() as (client, _factory):
        with publisher(client), publisher(client):
            with publisher(client) as third:
                assert closed_with(third) == OVER_CAP_CLOSE_CODE


def test_a_v1_publisher_gets_the_default_links_cap():
    too_many = {f"l{i}": f"tok{i}" for i in range(DEFAULT_LIMITS["links"] + 1)}
    with relay() as (client, _factory):
        with publisher(client) as pub:
            pub.send_text(json.dumps(links_frame(too_many)))
            assert closed_with(pub) == OVER_CAP_CLOSE_CODE




def test_the_daily_egress_default_is_360_gib():
    settings = settings_from_env({"RELAY_PUBLISH_TOKEN": "x"})
    assert settings.daily_egress_bytes == DEFAULT_DAILY_EGRESS_BYTES == 360 * 1024 ** 3
    tuned = settings_from_env({"RELAY_PUBLISH_TOKEN": "x",
                               "CARNIVORE_RELAY_DAILY_EGRESS_BYTES": "1000"})
    assert tuned.daily_egress_bytes == 1000


def test_the_breaker_trips_once_and_resets_on_the_next_utc_day():
    wall = [BEFORE_MIDNIGHT]
    breaker = EgressBreaker(100, wall=lambda: wall[0])
    with capture_logs() as logs:
        assert breaker.record(100) is False, "at the limit is not over it"
        assert not breaker.tripped()
        assert breaker.record(1) is True, "the crossing is reported once"
        assert breaker.record(1) is False
        assert breaker.tripped()
        wall[0] = AFTER_MIDNIGHT
        assert not breaker.tripped()
        assert breaker.record(50) is False
    events = [entry["event"] for entry in logs]
    assert events.count("relay_egress_breaker_tripped") == 1
    assert events.count("relay_egress_breaker_reset") == 1


def _watch_until_closed(client, link_id: str, pub) -> int:
    with client.websocket_connect(f"/watch/{link_id}",
                                  subprotocols=watch_protocols(SHARE_TOKEN)) as watcher:
        pub.send_text(json.dumps(data_frame(link_id, "x" * 200 + "\n")))
        return closed_with(watcher)


def test_the_breaker_closes_watchers_refuses_new_ones_and_keeps_publishers():
    wall = [BEFORE_MIDNIGHT]
    with relay(build_settings()) as (client, _factory):
        client.app.state.egress = EgressBreaker(100, wall=lambda: wall[0])
        with publisher(client) as pub:
            pub.send_text(json.dumps(links_frame({"l1": SHARE_TOKEN})))
            wait_for_links(client, 1)
            assert _watch_until_closed(client, "l1", pub) == OVERFLOW_CLOSE_CODE
            assert client.app.state.egress.tripped()

            with pytest.raises(WebSocketDisconnect) as refused:
                with client.websocket_connect(
                        "/watch/l1", subprotocols=watch_protocols(SHARE_TOKEN)):
                    pass
            assert refused.value.code == REFUSED_CLOSE_CODE
            assert client.get("/s/l1").status_code == 503
            assert client.get("/static/dist/app.css").status_code == 503

            health = client.get("/healthz").json()
            assert health["publishers"] == 1 and health["links"] == 1

            wall[0] = AFTER_MIDNIGHT
            with client.websocket_connect(
                    "/watch/l1", subprotocols=watch_protocols(SHARE_TOKEN)):
                pass
            assert client.get("/s/l1").status_code == 200


def test_viewer_page_and_asset_bytes_count_toward_the_breaker():
    with relay(build_settings()) as (client, _factory):
        client.app.state.egress = EgressBreaker(1_000_000_000)
        before = client.app.state.egress.day_bytes
        body = client.get("/static/dist/app.css").content
        assert client.app.state.egress.day_bytes - before == len(body) > 0


def test_the_metrics_line_is_embedded_metric_format():
    breaker = EgressBreaker(100, wall=lambda: BEFORE_MIDNIGHT)
    breaker.record(40)
    record = metrics_record(breaker)
    directive = record["_aws"]["CloudWatchMetrics"][0]
    assert directive["Namespace"] == METRIC_NAMESPACE
    assert directive["Dimensions"] == [["service"]]
    assert {m["Name"] for m in directive["Metrics"]} == {"bytes_out", "breaker_tripped"}
    assert record["_aws"]["Timestamp"] == BEFORE_MIDNIGHT * 1000
    assert record["service"] == "carnivore-relay"
    assert (record["bytes_out"], record["breaker_tripped"]) == (40, 0)
    assert metrics_record(breaker)["bytes_out"] == 0, "each line is one interval"
    breaker.record(100)
    assert metrics_record(breaker)["breaker_tripped"] == 1




@pytest.mark.asyncio
async def test_a_realistic_stream_for_an_hour_trips_nothing():
    clock = Clock()
    tenancy = Tenancy(clock=clock, wall=lambda: BEFORE_MIDNIGHT - 7200 + clock.now,
                      sleep=clock.sleep)
    breaker = EgressBreaker(DEFAULT_DAILY_EGRESS_BYTES,
                            wall=lambda: BEFORE_MIDNIGHT - 7200 + clock.now)
    for _ in range(3600):
        assert await tenancy.consume("t", 2048, DEFAULT_LIMITS) is None
        for _watcher in range(DEFAULT_LIMITS["wpl"]):
            assert breaker.record(2048) is False
        clock.now += 1.0
    assert clock.slept == [], "never throttled"
    assert not tenancy.quota_spent("t", DEFAULT_LIMITS)
    assert not breaker.tripped()
