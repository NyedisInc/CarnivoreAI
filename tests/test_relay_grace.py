
from __future__ import annotations

import asyncio
import json
import secrets
import time

import pytest
from starlette.websockets import WebSocketDisconnect

from relay.hub import RelayHub
from relay.protocol import LinkDeclaration
from src.core import relay_e2ee
from tests.relay_support import RecordingFactory, sha256_of
from tests.relay_v2_support import V2_TOKEN, Device, Issuer, SealedLink, links_v2, watch_v2
from tests.test_relay_sockets import build_settings, relay, wait_for_links
from tests.test_relay_v2_sockets import closed_with, connect

STOLEN = secrets.token_urlsafe(32)


def send_all(pub, frames) -> None:
    for frame in frames:
        pub.send_bytes(frame)


@pytest.fixture
def issuer() -> Issuer:
    return Issuer()


def grace_relay(issuer: Issuer, grace: float):
    return relay(build_settings(issuer_keys=issuer.pins, publisher_grace_seconds=grace))


def declare(pub, link_id: str, nonce: str, expires_at=None) -> None:
    frame = links_v2({link_id: V2_TOKEN}, {link_id: nonce})
    if expires_at is not None:
        frame["links"][0]["expires_at"] = expires_at
    pub.send_text(json.dumps(frame))


def wait_held(client, link_id: str, timeout: float = 5.0) -> None:
    hub = client.app.state.hub
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = hub._links.get(link_id)
        if state is not None and state.connection_id is None:
            return
        time.sleep(0.01)
    raise AssertionError(f"link {link_id} was never held in grace")


def test_the_same_device_reclaims_and_no_viewer_is_ever_closed(issuer):
    device = Device()
    link_id, nonce = device.link()
    with grace_relay(issuer, 30) as (client, _factory):
        with connect(client, device, issuer.token(device)) as pub:
            declare(pub, link_id, nonce)
            sealed = SealedLink(link_id)
            pub.send_bytes(sealed.open(170, 50))
            wait_for_links(client, 1)
            with client.websocket_connect(f"/watch/{link_id}",
                                          subprotocols=watch_v2(link_id)) as early:
                cached = sealed.read(early.receive_bytes())
                assert cached.kind == relay_e2ee.KIND_OPEN
                assert json.loads(cached.body)["cols"] == 170
                pub.send_bytes(sealed.open(170, 50))
                send_all(pub, sealed.data("before\n"))
                assert sealed.read(early.receive_bytes()).seq == 0
                assert b"before" in sealed.read(early.receive_bytes()).body
                pub.close()
                wait_held(client, link_id)
                with client.websocket_connect(
                        f"/watch/{link_id}", subprotocols=watch_v2(link_id)) as joiner:
                    held = sealed.read(joiner.receive_bytes())
                    assert held.kind == relay_e2ee.KIND_OPEN
                    assert json.loads(held.body)["rows"] == 50
                    with connect(client, device, issuer.token(device)) as back:
                        declare(back, link_id, nonce)
                        again = SealedLink(link_id)
                        back.send_bytes(again.open(170, 50))
                        send_all(back, again.data("after\n"))
                        for viewer in (early, joiner):
                            assert again.read(viewer.receive_bytes()).kind == relay_e2ee.KIND_OPEN
                            assert b"after" in again.read(viewer.receive_bytes()).body


def test_a_window_that_runs_out_ends_the_link_4410(issuer):
    device = Device()
    link_id, nonce = device.link()
    with grace_relay(issuer, 0.6) as (client, _factory):
        with connect(client, device, issuer.token(device)) as pub:
            declare(pub, link_id, nonce)
            wait_for_links(client, 1)
            with client.websocket_connect(f"/watch/{link_id}",
                                          subprotocols=watch_v2(link_id)) as viewer:
                pub.close()
                wait_held(client, link_id)
                held_at = time.monotonic()
                assert closed_with(viewer) == 4410
                assert time.monotonic() - held_at > 0.3
        wait_for_links(client, 0)


def test_a_reconnect_that_omits_the_link_ends_it_4410_at_once(issuer):
    device = Device()
    link_id, nonce = device.link()
    with grace_relay(issuer, 30) as (client, _factory):
        with connect(client, device, issuer.token(device)) as pub:
            declare(pub, link_id, nonce)
            wait_for_links(client, 1)
            with client.websocket_connect(f"/watch/{link_id}",
                                          subprotocols=watch_v2(link_id)) as viewer:
                pub.close()
                wait_held(client, link_id)
                with connect(client, device, issuer.token(device)) as back:
                    back.send_text(json.dumps(links_v2({}, {})))
                    assert closed_with(viewer, timeout=5.0) == 4410
        wait_for_links(client, 0)


def test_a_declared_expiry_ends_a_held_link_on_time(issuer):
    device = Device()
    link_id, nonce = device.link()
    with grace_relay(issuer, 30) as (client, _factory):
        with connect(client, device, issuer.token(device)) as pub:
            declare(pub, link_id, nonce, expires_at=int(time.time()) + 2)
            wait_for_links(client, 1)
            with client.websocket_connect(f"/watch/{link_id}",
                                          subprotocols=watch_v2(link_id)) as viewer:
                pub.close()
                assert closed_with(viewer, timeout=6.0) == 4410


def test_another_device_cannot_reclaim_a_held_link(issuer):
    owner, thief = Device(), Device()
    link_id, nonce = owner.link()
    with grace_relay(issuer, 30) as (client, _factory):
        with connect(client, owner, issuer.token(owner)) as pub:
            declare(pub, link_id, nonce)
            wait_for_links(client, 1)
            with client.websocket_connect(f"/watch/{link_id}",
                                          subprotocols=watch_v2(link_id)) as viewer:
                pub.close()
                wait_held(client, link_id)
                with connect(client, thief, issuer.token(thief)) as rogue:
                    rogue.send_text(json.dumps(links_v2({link_id: STOLEN}, {link_id: nonce})))
                    forged = SealedLink(link_id, STOLEN)
                    rogue.send_bytes(forged.open())
                    send_all(rogue, forged.data("injected\n"))
                    time.sleep(0.2)
                    assert client.app.state.hub._links[link_id].connection_id is None
                with pytest.raises(WebSocketDisconnect):
                    with client.websocket_connect(f"/watch/{link_id}",
                                                  subprotocols=watch_v2(link_id, STOLEN)):
                        pass
                with connect(client, owner, issuer.token(owner)) as back:
                    declare(back, link_id, nonce)
                    owner_link = SealedLink(link_id)
                    back.send_bytes(owner_link.open())
                    send_all(back, owner_link.data("owner\n"))
                    assert owner_link.read(viewer.receive_bytes()).seq == 0
                    assert b"owner" in owner_link.read(viewer.receive_bytes()).body


def test_a_revoked_device_gets_no_window(issuer):
    device = Device()
    link_id, nonce = device.link()
    until = int(time.time()) + 600
    with grace_relay(issuer, 30) as (client, _factory):
        app = client.app
        with connect(client, device, issuer.token(device)) as pub:
            declare(pub, link_id, nonce)
            wait_for_links(client, 1)
            with client.websocket_connect(f"/watch/{link_id}",
                                          subprotocols=watch_v2(link_id)) as viewer:
                app.state.denylist.apply(issuer.denylist(1, [{"sub": device.device_id,
                                                               "until": until}]), issuer.pins)
                from tests.test_relay_v2_sockets import _close_denied_async
                assert client.portal.call(_close_denied_async, app) == 1
                assert closed_with(pub) == 4403
                assert closed_with(viewer, timeout=5.0) == 4410


def test_a_device_revoked_while_down_loses_its_held_links(issuer):
    device = Device()
    link_id, nonce = device.link()
    until = int(time.time()) + 600
    with grace_relay(issuer, 30) as (client, _factory):
        app = client.app
        with connect(client, device, issuer.token(device)) as pub:
            declare(pub, link_id, nonce)
            wait_for_links(client, 1)
            with client.websocket_connect(f"/watch/{link_id}",
                                          subprotocols=watch_v2(link_id)) as viewer:
                pub.close()
                wait_held(client, link_id)
                app.state.denylist.apply(issuer.denylist(1, [{"sub": device.device_id,
                                                               "until": until}]), issuer.pins)
                from tests.test_relay_v2_sockets import _close_denied_async
                assert client.portal.call(_close_denied_async, app) == 0
                assert closed_with(viewer, timeout=5.0) == 4410
        wait_for_links(client, 0)


def test_a_disabled_tenant_ends_its_live_links_with_no_window(issuer):
    device = Device()
    link_id, nonce = device.link()
    until = int(time.time()) + 600
    with grace_relay(issuer, 30) as (client, _factory):
        app = client.app
        with connect(client, device, issuer.token(device)) as pub:
            declare(pub, link_id, nonce)
            wait_for_links(client, 1)
            with client.websocket_connect(f"/watch/{link_id}",
                                          subprotocols=watch_v2(link_id)) as viewer:
                app.state.denylist.apply(issuer.denylist(1, [{"ten": device.ten,
                                                               "until": until}]), issuer.pins)
                from tests.test_relay_v2_sockets import _close_denied_async
                assert client.portal.call(_close_denied_async, app) == 1
                assert closed_with(pub) == 4403
                assert closed_with(viewer, timeout=5.0) == 4410
        wait_for_links(client, 0)


def test_a_held_link_and_its_watchers_still_count_against_the_caps():
    asyncio.run(_held_link_counts())


async def _held_link_counts() -> None:
    hub = RelayHub(redactor_factory=RecordingFactory(), max_watcher_chunks=8,
                   max_watcher_bytes=1 << 16, idle_flush_ms=50, max_watchers_per_link=4,
                   max_watchers_total=1, grace_seconds=30)
    decl = LinkDeclaration(link_id="l1", token_sha256=sha256_of("t"))
    other = LinkDeclaration(link_id="l2", token_sha256=sha256_of("u"))
    hub.declare("c1", [decl], publisher_id="sub:a", tenant="ten", max_watchers=4)
    hub.declare("c2", [other], publisher_id="sub:b", tenant="ten", max_watchers=4)
    assert hub.add_watcher("l1") is not None
    assert hub.drop_publisher("c1", grace=True) == []
    assert hub.tenant_link_count("ten", excluding_owner="sub:b") == 1
    assert hub.watcher_refusal("l2") == "total_watcher_cap"
    hub.shutdown()
    await asyncio.sleep(0)


def test_expires_at_is_optional_and_a_bad_one_refuses_the_frame():
    from relay.protocol import ProtocolError, parse_links_frame
    device = Device()
    link_id, nonce = device.link()
    frame = links_v2({link_id: V2_TOKEN}, {link_id: nonce})
    assert parse_links_frame(frame, device_id=device.device_id)[0].expires_at is None
    frame["links"][0]["expires_at"] = 1_900_000_000
    assert parse_links_frame(frame, device_id=device.device_id)[0].expires_at == 1_900_000_000
    for bad in (True, 0, -5, "1900000000", 1.5, 1 << 41):
        frame["links"][0]["expires_at"] = bad
        with pytest.raises(ProtocolError):
            parse_links_frame(frame, device_id=device.device_id)


def test_the_window_is_90_seconds_unless_the_environment_says_otherwise():
    from relay.config import settings_from_env
    assert settings_from_env({"RELAY_PUBLISH_TOKEN": "x"}).publisher_grace_seconds == 90
    assert settings_from_env({"RELAY_PUBLISH_TOKEN": "x",
                              "RELAY_PUBLISHER_GRACE_SECONDS": "15"}).publisher_grace_seconds == 15


def test_the_mac_declares_each_links_expiry_on_v2_and_the_relay_reads_it():
    from relay.protocol import parse_links_frame
    from src.core import relay_protocol as proto
    from src.core.relay_identity.publish_auth import DeviceAuth
    device = Device()
    link_id, nonce = device.link()
    auth = DeviceAuth.__new__(DeviceAuth)
    decl = proto.LinkDeclaration(link_id=link_id, token_sha256=sha256_of(V2_TOKEN),
                                 session_id="ses_1", nonce=nonce, expires_at=1_900_000_000)
    frame = json.loads(auth.links_frame([decl], "unused"))
    assert frame["links"][0]["expires_at"] == 1_900_000_000
    assert parse_links_frame(frame, device_id=device.device_id)[0].expires_at == 1_900_000_000
    bare = json.loads(auth.links_frame(
        [proto.LinkDeclaration(link_id=link_id, token_sha256=sha256_of(V2_TOKEN),
                               session_id="ses_1", nonce=nonce)], "unused"))
    assert "expires_at" not in bare["links"][0]
