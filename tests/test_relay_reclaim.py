
from __future__ import annotations

import json
import time

import pytest
from starlette.websockets import WebSocketDisconnect
from structlog.testing import capture_logs

from relay.bounded import REASON_ENDED
from relay.protocol import ProtocolError, parse_publisher_id
from src.core import relay_protocol as proto
from src.core import relay_publisher
from tests.relay_support import PUBLISHER_ID, RecordingFactory, data_frame, links_frame, watch_protocols
from tests.test_relay_hardening import OTHER
from tests.test_relay_hub import DIGEST_A, DIGEST_B, build_hub, declaration
from tests.test_relay_publisher import DECL, _FakeConnection, _legacy, _registry, _until
from tests.test_relay_sockets import SHARE_TOKEN, publisher, relay, wait_for_links
from tests.test_spectator_scrub import _StarringRedactor




def test_the_same_publisher_on_a_new_socket_reclaims_without_ending_watchers():
    factory = RecordingFactory()
    hub = build_hub(factory)
    hub.declare("old", [declaration("l1")], publisher_id=PUBLISHER_ID)
    watcher = hub.add_watcher("l1")
    redactor = hub.redactor_for("l1")

    assert hub.declare("new", [declaration("l1")], publisher_id=PUBLISHER_ID) == []
    assert hub.drop_publisher("old") == []

    assert hub.link_ids() == ["l1"]
    assert watcher.stream.reason is None
    assert hub.redactor_for("l1") is redactor
    assert len(factory.made) == 1


@pytest.mark.asyncio
async def test_after_a_reclaim_only_the_new_socket_may_publish():
    hub = build_hub(RecordingFactory())
    hub.declare("old", [declaration("l1")], publisher_id=PUBLISHER_ID)
    hub.declare("new", [declaration("l1")], publisher_id=PUBLISHER_ID)
    assert await hub.publish("old", "l1", "stale") is False
    assert await hub.publish("new", "l1", "fresh") is True
    hub.shutdown()


def test_a_different_publisher_is_still_refused_while_the_owner_is_connected():
    hub = build_hub(RecordingFactory())
    hub.declare("owner", [declaration("l1", DIGEST_A)], publisher_id=PUBLISHER_ID)
    watcher = hub.add_watcher("l1")
    with capture_logs() as logs:
        hub.declare("intruder", [declaration("l1", DIGEST_B)], publisher_id=OTHER)
    assert hub.digest_for("l1") == DIGEST_A
    assert watcher.stream.reason is None
    assert [e["event"] for e in logs] == ["relay_link_redeclare_refused"]
    assert not any(PUBLISHER_ID in str(v) or OTHER in str(v) for e in logs for v in e.values())


def test_a_reclaim_with_a_rotated_digest_ends_the_old_watchers():
    hub = build_hub(RecordingFactory())
    hub.declare("old", [declaration("l1", DIGEST_A)], publisher_id=PUBLISHER_ID)
    watcher = hub.add_watcher("l1")
    assert hub.declare("new", [declaration("l1", DIGEST_B)], publisher_id=PUBLISHER_ID) == ["l1"]
    assert watcher.stream.reason == REASON_ENDED
    assert hub.digest_for("l1") == DIGEST_B


def test_an_identical_redeclare_is_a_silent_no_op_for_watchers():
    factory = RecordingFactory()
    hub = build_hub(factory)
    hub.declare("c1", [declaration("l1")], publisher_id=PUBLISHER_ID)
    watcher = hub.add_watcher("l1")
    with capture_logs() as logs:
        for _ in range(3):
            assert hub.declare("c1", [declaration("l1")], publisher_id=PUBLISHER_ID) == []
    assert logs == []
    assert watcher.stream.reason is None and len(factory.made) == 1


def test_the_publisher_id_is_required_and_must_be_long_enough():
    assert parse_publisher_id({"publisher_id": PUBLISHER_ID}) == PUBLISHER_ID
    for bad in (None, 7, "", "short", "x" * 31, "p" * 129, "p" * 31 + "!"):
        with pytest.raises(ProtocolError):
            parse_publisher_id({"publisher_id": bad})




def test_a_returning_publisher_keeps_the_viewer_through_the_old_sockets_close():
    with relay() as (client, _factory):
        with publisher(client) as old, publisher(client) as new:
            old.send_text(json.dumps(links_frame({"l1": SHARE_TOKEN})))
            wait_for_links(client, 1)
            with client.websocket_connect(
                "/watch/l1", subprotocols=watch_protocols(SHARE_TOKEN)
            ) as viewer:
                new.send_text(json.dumps(links_frame({"l1": SHARE_TOKEN})))
                new.send_text(json.dumps(data_frame("l1", "marker-one")))
                assert viewer.receive_bytes().decode() == "marker-one"
                old.close()
                new.send_text(json.dumps(data_frame("l1", "marker-two")))
                assert viewer.receive_bytes().decode() == "marker-two"
                assert client.get("/healthz").json()["links"] == 1


def test_a_links_frame_without_a_publisher_id_is_refused():
    with relay() as (client, _factory):
        with publisher(client) as pub:
            frame = links_frame({"l1": SHARE_TOKEN})
            del frame["publisher_id"]
            pub.send_text(json.dumps(frame))
            pub.send_text(json.dumps(data_frame("l1", "x")))
            with pytest.raises(WebSocketDisconnect) as closed:
                pub.receive_text()
            assert closed.value.code == 4400
            assert client.get("/healthz").json()["links"] == 0


def test_one_socket_cannot_switch_publisher_ids():
    with relay() as (client, _factory):
        with publisher(client) as pub:
            pub.send_text(json.dumps(links_frame({"l1": SHARE_TOKEN})))
            wait_for_links(client, 1)
            with capture_logs() as logs:
                pub.send_text(json.dumps(links_frame({"l2": "t2"}, publisher=OTHER)))
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline and "relay_links_frame_rejected" not in [
                    e["event"] for e in logs
                ]:
                    time.sleep(0.01)
            assert "relay_links_frame_rejected" in [e["event"] for e in logs]
            assert client.get("/healthz").json()["links"] == 1




@pytest.mark.asyncio
async def test_the_mac_redeclares_on_every_refresh_and_every_connection():
    registry = _registry()
    conns = [_FakeConnection(), _FakeConnection()]
    dialled = []

    def connector(url, dial):
        dialled.append(conns[len(dialled)])
        return dialled[-1]

    async def decls():
        return [DECL]

    async def no_wait(_seconds):
        pass

    publisher_ = relay_publisher.RelayPublisher(
        url="wss://r/publish", credentials=_legacy(), registry=registry,
        declarations=decls, connector=connector,
        redactor_factory=_StarringRedactor, refresh_seconds=0.02, sleep=no_wait,
    )
    publisher_.start()
    first = conns[0]
    assert await _until(lambda: len(first.sent) >= 3)
    frames = [json.loads(f) for f in first.sent]
    assert all(f["type"] == "links" and f["links"][0]["link_id"] == "lnk_1" for f in frames)
    first._closed.set()
    assert await _until(lambda: len(dialled) == 2 and conns[1].sent)
    await publisher_.aclose()
    second = json.loads(conns[1].sent[0])
    assert second["type"] == "links"
    ids = {f["publisher_id"] for f in frames} | {second["publisher_id"]}
    assert len(ids) == 1 and len(ids.pop()) == 32
    assert proto.new_publisher_id() != frames[0]["publisher_id"]
