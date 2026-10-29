
from __future__ import annotations

import asyncio
import json
import secrets
import time
from contextlib import contextmanager
from typing import Iterator

import anyio
import pytest
from starlette.websockets import WebSocketDisconnect

from relay.app import close_denied
from relay.bounded import REFUSED_CLOSE_CODE
from tests.relay_v2_support import (
    DEFAULT_LIM,
    V2,
    V2_TOKEN,
    Device,
    Issuer,
    SealedLink,
    links_v2,
    watch_v2,
)
from tests.test_relay_sockets import build_settings, relay, wait_for_links


STOLEN = secrets.token_urlsafe(32)


@pytest.fixture
def issuer() -> Issuer:
    return Issuer()


@contextmanager
def v2_relay(issuer: Issuer) -> Iterator[tuple]:
    with relay(build_settings(issuer_keys=issuer.pins)) as pair:
        yield pair


def connect(client, device: Device, token: str, **kw):
    return client.websocket_connect("/publish", headers=device.headers(token, **kw),
                                    subprotocols=V2)


def closed_with(socket, timeout: float = 5.0) -> int:
    async def bounded() -> int:
        with anyio.fail_after(timeout):
            while True:
                message = await socket._send_rx.receive()
                if message["type"] == "websocket.close":
                    return message.get("code", 1000)

    return socket.portal.call(bounded)


def test_a_device_publishes_a_derived_link_that_a_viewer_watches(issuer):
    device = Device()
    link_id, nonce = device.link()
    with v2_relay(issuer) as (client, _factory):
        with connect(client, device, issuer.token(device)) as pub:
            pub.send_text(json.dumps(links_v2({link_id: V2_TOKEN}, {link_id: nonce})))
            wait_for_links(client, 1)
            with client.websocket_connect(f"/watch/{link_id}",
                                          subprotocols=watch_v2(link_id)) as viewer:
                sealed = SealedLink(link_id)
                pub.send_bytes(sealed.open())
                for frame in sealed.data("hello v2\n"):
                    pub.send_bytes(frame)
                assert sealed.read(viewer.receive_bytes()).seq == 0
                assert b"hello v2" in sealed.read(viewer.receive_bytes()).body


def test_a_link_id_not_derived_from_the_device_is_refused(issuer):
    device = Device()
    good, good_nonce = device.link()
    _, nonce = device.link()
    with v2_relay(issuer) as (client, _factory):
        with connect(client, device, issuer.token(device)) as pub:
            pub.send_text(json.dumps(links_v2({"lnk_chosen": V2_TOKEN},
                                              {"lnk_chosen": nonce})))
            time.sleep(0.1)
            assert client.get("/healthz").json()["links"] == 0
            pub.send_text(json.dumps(links_v2({good: V2_TOKEN}, {good: good_nonce})))
            wait_for_links(client, 1)


def test_a_second_device_cannot_claim_the_first_devices_link(issuer):
    owner, thief = Device(), Device()
    link_id, nonce = owner.link()
    with v2_relay(issuer) as (client, _factory):
        with connect(client, thief, issuer.token(thief)) as rogue:
            rogue.send_text(json.dumps(links_v2({link_id: STOLEN}, {link_id: nonce})))
            time.sleep(0.1)
            with connect(client, owner, issuer.token(owner)) as pub:
                pub.send_text(json.dumps(links_v2({link_id: V2_TOKEN}, {link_id: nonce})))
                wait_for_links(client, 1)
                with client.websocket_connect(f"/watch/{link_id}",
                                              subprotocols=watch_v2(link_id)) as viewer:
                    sealed = SealedLink(link_id)
                    pub.send_bytes(sealed.open())
                    for frame in sealed.data("still mine\n"):
                        pub.send_bytes(frame)
                    viewer.receive_bytes()
                    assert b"still mine" in sealed.read(viewer.receive_bytes()).body
                with pytest.raises(WebSocketDisconnect):
                    with client.websocket_connect(f"/watch/{link_id}",
                                                  subprotocols=watch_v2(link_id, STOLEN)):
                        pass


def test_a_bad_token_never_gets_a_socket(issuer):
    device = Device()
    with v2_relay(issuer) as (client, _factory):
        with pytest.raises(WebSocketDisconnect) as refused:
            with connect(client, device, Issuer().token(device)):
                pass
        assert refused.value.code == REFUSED_CLOSE_CODE


def test_a_replayed_handshake_is_refused(issuer):
    device = Device()
    token = issuer.token(device)
    headers = device.headers(token)
    with v2_relay(issuer) as (client, _factory):
        with client.websocket_connect("/publish", headers=headers, subprotocols=V2):
            pass
        with pytest.raises(WebSocketDisconnect) as refused:
            with client.websocket_connect("/publish", headers=headers, subprotocols=V2):
                pass
        assert refused.value.code == REFUSED_CLOSE_CODE


def test_v2_is_refused_when_no_issuer_key_is_pinned():
    device = Device()
    with relay() as (client, _factory):
        with pytest.raises(WebSocketDisconnect):
            with connect(client, device, Issuer().token(device)):
                pass


def test_the_connection_cap_closes_4413(issuer):
    device = Device()
    lim = {**DEFAULT_LIM, "pubs": 1}
    with v2_relay(issuer) as (client, _factory):
        with connect(client, device, issuer.token(device, lim=lim)):
            with connect(client, device, issuer.token(device, lim=lim)) as second:
                assert closed_with(second) == 4413


def test_the_links_cap_closes_4413(issuer):
    device = Device()
    (a, na), (b, nb) = device.link(), device.link()
    lim = {**DEFAULT_LIM, "links": 1}
    with v2_relay(issuer) as (client, _factory):
        with connect(client, device, issuer.token(device, lim=lim)) as pub:
            pub.send_text(json.dumps(links_v2({a: V2_TOKEN, b: V2_TOKEN}, {a: na, b: nb})))
            assert closed_with(pub) == 4413


def test_the_watchers_per_link_cap_follows_the_token(issuer):
    device = Device()
    link_id, nonce = device.link()
    lim = {**DEFAULT_LIM, "wpl": 1}
    with v2_relay(issuer) as (client, _factory):
        with connect(client, device, issuer.token(device, lim=lim)) as pub:
            pub.send_text(json.dumps(links_v2({link_id: V2_TOKEN}, {link_id: nonce})))
            wait_for_links(client, 1)
            protocols = watch_v2(link_id)
            with client.websocket_connect(f"/watch/{link_id}", subprotocols=protocols):
                with pytest.raises(WebSocketDisconnect):
                    with client.websocket_connect(f"/watch/{link_id}", subprotocols=protocols):
                        pass


def test_the_daily_quota_closes_4402(issuer):
    device = Device()
    link_id, nonce = device.link()
    lim = {**DEFAULT_LIM, "bytes_day": 8}
    with v2_relay(issuer) as (client, _factory):
        with connect(client, device, issuer.token(device, lim=lim)) as pub:
            pub.send_text(json.dumps(links_v2({link_id: V2_TOKEN}, {link_id: nonce})))
            pub.send_bytes(SealedLink(link_id).open())
            assert closed_with(pub) == 4402
        with connect(client, device, issuer.token(device, lim=lim)) as again:
            assert closed_with(again) == 4402, "a spent quota refuses a new connection"


def test_the_version_floor_closes_4426(issuer):
    device = Device()
    with v2_relay(issuer) as (client, _factory):
        with connect(client, device, issuer.token(device, min="9.0.0")) as pub:
            assert closed_with(pub) == 4426


def test_a_denylisted_device_is_closed_4403_at_the_handshake_and_while_live(issuer):
    device, denied_later = Device(), Device()
    until = int(time.time()) + 600
    with v2_relay(issuer) as (client, _factory):
        app = client.app
        app.state.denylist.apply(issuer.denylist(1, [{"sub": device.device_id,
                                                       "until": until}]), issuer.pins)
        with connect(client, device, issuer.token(device)) as pub:
            assert closed_with(pub) == 4403
        with connect(client, denied_later, issuer.token(denied_later)) as live:
            live.send_text(json.dumps(links_v2({}, {})))
            app.state.denylist.apply(issuer.denylist(2, [{"ten": denied_later.ten,
                                                           "until": until}]), issuer.pins)
            assert client.portal.call(_close_denied_async, app) == 1
            assert closed_with(live) == 4403


async def _close_denied_async(app) -> int:
    return close_denied(app)


def test_a_token_left_to_expire_closes_4440_and_a_reauth_moves_the_deadline(issuer):
    device = Device()
    soon = int(time.time()) - 59
    with v2_relay(issuer) as (client, _factory):
        with connect(client, device, issuer.token(device, exp=soon)) as pub:
            pub.send_text(json.dumps(links_v2({}, {})))
            started = time.monotonic()
            assert closed_with(pub) == 4440
            assert time.monotonic() - started < 5
        soon = int(time.time()) - 58
        with connect(client, device, issuer.token(device, exp=soon)) as pub:
            pub.send_text(json.dumps(links_v2({}, {})))
            pub.send_text(json.dumps(device.reauth(issuer.token(device))))
            time.sleep(2.5)
            assert client.get("/healthz").json()["publishers"] == 1, "closed despite reauth"


@pytest.mark.asyncio
async def test_a_publisher_that_never_stops_sending_is_still_closed_4440():
    from relay import publish_socket, publish_v2
    from relay.auth import RelayClaims

    class Buffered:

        def __init__(self) -> None:
            self.queue: asyncio.Queue = asyncio.Queue()
            for _ in range(1000):
                self.queue.put_nowait('{"type": "noise"}')

        async def receive_text(self) -> str:
            return await self.queue.get()

    claims = RelayClaims(sub="a" * 26, dpk=bytes(32), ten="t", jti="j",
                         exp=int(time.time()) - 3600, lim={}, min="0")
    principal = publish_v2.Principal(claims=claims, connection_id="c")
    with pytest.raises(publish_socket._Closing) as closing:
        for _ in range(500):
            await publish_socket._receive(Buffered(), principal)
            await asyncio.sleep(0)
    assert closing.value.code == 4440


def test_a_reauth_below_its_new_floor_closes_4426(issuer):
    device = Device()
    with v2_relay(issuer) as (client, _factory):
        with connect(client, device, issuer.token(device)) as pub:
            pub.send_text(json.dumps(links_v2({}, {})))
            pub.send_text(json.dumps(device.reauth(issuer.token(device, min="2.0.0"))))
            assert closed_with(pub) == 4426
