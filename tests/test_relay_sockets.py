
from __future__ import annotations

import hmac as real_hmac
import json
import time
from contextlib import contextmanager
from typing import Iterator, Optional

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from relay import auth as relay_auth
from relay.app import create_app
from relay.bounded import (
    ENDED_CLOSE_CODE,
    OVERFLOW_CLOSE_CODE,
    REFUSED_CLOSE_CODE,
)
from relay.config import RelaySettings
from relay.protocol import PUBLISH_SUBPROTOCOL
from tests.relay_support import (
    STUB_REPLACEMENT,
    STUB_SECRET,
    RecordingFactory,
    RecordingHmac,
    data_frame,
    links_frame,
    watch_protocols,
)

PUBLISH_TOKEN = "publish-token-value"
SHARE_TOKEN = "share-token-value"


def build_settings(**overrides) -> RelaySettings:
    base = {
        "publish_token": PUBLISH_TOKEN,
        "tail_bytes": 2048,
        "idle_flush_ms": 50,
        "port": 8080,
    }
    base.update(overrides)
    return RelaySettings(**base)


@contextmanager
def relay(
    settings: Optional[RelaySettings] = None, tail: int = 0
) -> Iterator[tuple]:
    factory = RecordingFactory(tail=tail)
    app = create_app(settings or build_settings(), redactor_factory=factory)
    with TestClient(app) as client:
        yield client, factory


@contextmanager
def publisher(client: TestClient, token: str = PUBLISH_TOKEN) -> Iterator:
    with client.websocket_connect(
        "/publish",
        headers={"Authorization": f"Bearer {token}"},
        subprotocols=[PUBLISH_SUBPROTOCOL],
    ) as socket:
        yield socket


def wait_for_links(client: TestClient, expected: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    seen = None
    while time.monotonic() < deadline:
        seen = client.get("/healthz").json()["links"]
        if seen == expected:
            return
        time.sleep(0.01)
    raise AssertionError(
        f"relay never reported {expected} live links; last saw {seen}"
    )




def test_healthz_answers_with_no_publisher_connected():
    with relay() as (client, _factory):
        response = client.get("/healthz")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["publishers"] == 0
        assert body["links"] == 0


def test_healthz_needs_no_credential():
    with relay() as (client, _factory):
        assert client.get("/healthz").status_code == 200




def test_publisher_with_wrong_token_is_refused():
    with relay() as (client, _factory):
        with pytest.raises(WebSocketDisconnect) as refused:
            with client.websocket_connect(
                "/publish",
                headers={"Authorization": "Bearer not-the-token"},
                subprotocols=[PUBLISH_SUBPROTOCOL],
            ):
                pass
        assert refused.value.code == REFUSED_CLOSE_CODE


def test_publisher_with_no_token_is_refused():
    with relay() as (client, _factory):
        with pytest.raises(WebSocketDisconnect) as refused:
            with client.websocket_connect(
                "/publish", subprotocols=[PUBLISH_SUBPROTOCOL]
            ):
                pass
        assert refused.value.code == REFUSED_CLOSE_CODE


def test_publisher_with_right_token_is_accepted_and_can_declare():
    with relay() as (client, _factory):
        with publisher(client) as pub:
            pub.send_text(json.dumps(links_frame({"l1": SHARE_TOKEN})))
            wait_for_links(client, 1)
            assert client.get("/healthz").json()["publishers"] == 1


def test_publisher_token_compare_uses_hmac_compare_digest(monkeypatch):
    recorder = RecordingHmac(real_hmac.compare_digest)
    monkeypatch.setattr(relay_auth, "hmac", recorder)
    with relay() as (client, _factory):
        with publisher(client) as pub:
            pub.send_text(json.dumps(links_frame({"l1": SHARE_TOKEN})))
            wait_for_links(client, 1)
    assert recorder.calls, "no constant-time comparison was performed"
    assert recorder.saw(PUBLISH_TOKEN.encode(), PUBLISH_TOKEN.encode())


def test_watcher_token_compare_uses_hmac_compare_digest(monkeypatch):
    recorder = RecordingHmac(real_hmac.compare_digest)
    with relay() as (client, _factory):
        with publisher(client) as pub:
            pub.send_text(json.dumps(links_frame({"l1": SHARE_TOKEN})))
            wait_for_links(client, 1)
            monkeypatch.setattr(relay_auth, "hmac", recorder)
            with client.websocket_connect(
                "/watch/l1", subprotocols=watch_protocols(SHARE_TOKEN)
            ):
                pass
    assert recorder.calls, "no constant-time comparison was performed"
    left, right = recorder.calls[0]
    assert left == right
    assert len(left) == 64 and left == left.lower()




def test_watcher_with_matching_token_is_accepted():
    with relay() as (client, _factory):
        with publisher(client) as pub:
            pub.send_text(json.dumps(links_frame({"l1": SHARE_TOKEN})))
            wait_for_links(client, 1)
            with client.websocket_connect(
                "/watch/l1", subprotocols=watch_protocols(SHARE_TOKEN)
            ) as watcher:
                pub.send_text(json.dumps(data_frame("l1", "plain output")))
                assert watcher.receive_bytes().decode() == "plain output"


def test_wrong_token_and_unknown_link_are_indistinguishable():
    with relay() as (client, _factory):
        with publisher(client) as pub:
            pub.send_text(json.dumps(links_frame({"l1": SHARE_TOKEN})))
            wait_for_links(client, 1)

            with pytest.raises(WebSocketDisconnect) as wrong_token:
                with client.websocket_connect(
                    "/watch/l1", subprotocols=watch_protocols("not-the-token")
                ):
                    pass

            with pytest.raises(WebSocketDisconnect) as unknown_link:
                with client.websocket_connect(
                    "/watch/no-such-link",
                    subprotocols=watch_protocols(SHARE_TOKEN),
                ):
                    pass

    assert wrong_token.value.code == REFUSED_CLOSE_CODE
    assert unknown_link.value.code == REFUSED_CLOSE_CODE
    assert wrong_token.value.code == unknown_link.value.code
    assert wrong_token.value.reason == unknown_link.value.reason


def test_watcher_with_no_token_is_refused():
    with relay() as (client, _factory):
        with publisher(client) as pub:
            pub.send_text(json.dumps(links_frame({"l1": SHARE_TOKEN})))
            wait_for_links(client, 1)
            with pytest.raises(WebSocketDisconnect) as refused:
                with client.websocket_connect(
                    "/watch/l1", subprotocols=[watch_protocols("x")[0]]
                ):
                    pass
    assert refused.value.code == REFUSED_CLOSE_CODE




def test_payload_reaches_the_watcher_only_after_redaction():
    raw = f"aws_secret={STUB_SECRET} done"
    redacted = f"aws_secret={STUB_REPLACEMENT} done"
    with relay() as (client, factory):
        with publisher(client) as pub:
            pub.send_text(json.dumps(links_frame({"l1": SHARE_TOKEN})))
            wait_for_links(client, 1)
            with client.websocket_connect(
                "/watch/l1", subprotocols=watch_protocols(SHARE_TOKEN)
            ) as watcher:
                pub.send_text(json.dumps(data_frame("l1", raw)))
                received = watcher.receive_bytes().decode()

    assert received == redacted
    assert STUB_SECRET not in received
    assert factory.made[0].fed == [raw]


def test_one_redactor_per_link_never_one_shared():
    with relay(tail=4) as (client, factory):
        with publisher(client) as pub:
            pub.send_text(
                json.dumps(links_frame({"l1": SHARE_TOKEN, "l2": "other-token"}))
            )
            wait_for_links(client, 2)
            with client.websocket_connect(
                "/watch/l2", subprotocols=watch_protocols("other-token")
            ) as watcher_b:
                pub.send_text(json.dumps(data_frame("l1", "AAAAAAAAAA")))
                pub.send_text(json.dumps(data_frame("l2", "BBBBBBBBBB")))
                received = watcher_b.receive_bytes().decode()

    assert len(factory.made) == 2
    assert factory.made[0] is not factory.made[1]
    assert set(received) == {"B"}
    assert "A" not in received


def test_quiet_link_releases_its_held_tail():
    settings = build_settings(idle_flush_ms=20)
    with relay(settings, tail=6) as (client, factory):
        with publisher(client) as pub:
            pub.send_text(json.dumps(links_frame({"l1": SHARE_TOKEN})))
            wait_for_links(client, 1)
            with client.websocket_connect(
                "/watch/l1", subprotocols=watch_protocols(SHARE_TOKEN)
            ) as watcher:
                pub.send_text(json.dumps(data_frame("l1", "0123456789")))
                first = watcher.receive_bytes().decode()
                assert first == "0123"
                assert watcher.receive_bytes().decode() == "456789"
    assert factory.made[0].flush_calls >= 1




def test_dropping_a_link_closes_its_watchers_with_share_ended():
    with relay() as (client, _factory):
        with publisher(client) as pub:
            pub.send_text(json.dumps(links_frame({"l1": SHARE_TOKEN})))
            wait_for_links(client, 1)
            with pytest.raises(WebSocketDisconnect) as ended:
                with client.websocket_connect(
                    "/watch/l1", subprotocols=watch_protocols(SHARE_TOKEN)
                ) as watcher:
                    pub.send_text(json.dumps(links_frame({})))
                    watcher.receive_bytes().decode()
    assert ended.value.code == ENDED_CLOSE_CODE


def test_share_ended_and_refused_never_collapse():
    with relay() as (client, _factory):
        with publisher(client) as pub:
            pub.send_text(json.dumps(links_frame({"l1": SHARE_TOKEN})))
            wait_for_links(client, 1)

            with pytest.raises(WebSocketDisconnect) as ended:
                with client.websocket_connect(
                    "/watch/l1", subprotocols=watch_protocols(SHARE_TOKEN)
                ) as watcher:
                    pub.send_text(json.dumps(links_frame({})))
                    watcher.receive_bytes().decode()

            with pytest.raises(WebSocketDisconnect) as refused:
                with client.websocket_connect(
                    "/watch/l1", subprotocols=watch_protocols(SHARE_TOKEN)
                ):
                    pass

    assert ended.value.code == ENDED_CLOSE_CODE
    assert refused.value.code == REFUSED_CLOSE_CODE
    assert ended.value.code != refused.value.code


def test_publisher_going_away_ends_its_watchers():
    with relay() as (client, _factory):
        with pytest.raises(WebSocketDisconnect) as ended:
            with publisher(client) as pub:
                pub.send_text(json.dumps(links_frame({"l1": SHARE_TOKEN})))
                wait_for_links(client, 1)
                with client.websocket_connect(
                    "/watch/l1", subprotocols=watch_protocols(SHARE_TOKEN)
                ) as watcher:
                    pub.close()
                    watcher.receive_bytes().decode()
    assert ended.value.code == ENDED_CLOSE_CODE




def test_watcher_overflow_disconnects_and_never_truncates():
    settings = build_settings(max_watcher_bytes=8)
    with relay(settings) as (client, _factory):
        with publisher(client) as pub:
            pub.send_text(json.dumps(links_frame({"l1": SHARE_TOKEN})))
            wait_for_links(client, 1)
            with pytest.raises(WebSocketDisconnect) as overflowed:
                with client.websocket_connect(
                    "/watch/l1", subprotocols=watch_protocols(SHARE_TOKEN)
                ) as watcher:
                    pub.send_text(json.dumps(data_frame("l1", "x" * 200)))
                    watcher.receive_bytes().decode()
    assert overflowed.value.code == OVERFLOW_CLOSE_CODE
    assert overflowed.value.code != ENDED_CLOSE_CODE




def test_first_frame_must_be_a_links_frame():
    with relay() as (client, _factory):
        with pytest.raises(WebSocketDisconnect) as refused:
            with publisher(client) as pub:
                pub.send_text(json.dumps(data_frame("l1", "output")))
                pub.receive_text()
    assert refused.value.code == 4400


def test_a_malformed_links_frame_leaves_the_previous_set_standing():
    with relay() as (client, _factory):
        with publisher(client) as pub:
            pub.send_text(json.dumps(links_frame({"l1": SHARE_TOKEN})))
            wait_for_links(client, 1)
            pub.send_text(json.dumps({"type": "links", "links": "not a list"}))
            pub.send_text(json.dumps(data_frame("l1", "still alive")))
            with client.websocket_connect(
                "/watch/l1", subprotocols=watch_protocols(SHARE_TOKEN)
            ) as watcher:
                pub.send_text(json.dumps(data_frame("l1", "still alive")))
                assert watcher.receive_bytes().decode() == "still alive"
            assert client.get("/healthz").json()["links"] == 1




def test_a_joiner_gets_the_size_as_text_output_as_binary_and_the_publisher_a_join():
    lookalike = '{"type":"terminal_size","cols":3,"rows":2}'
    with relay() as (client, _factory):
        with publisher(client) as pub:
            pub.send_text(json.dumps(links_frame({"l1": SHARE_TOKEN})))
            pub.send_text(json.dumps({"type": "size", "link_id": "l1", "cols": 170,
                                      "rows": 50}))
            wait_for_links(client, 1)
            with client.websocket_connect(
                "/watch/l1", subprotocols=watch_protocols(SHARE_TOKEN)
            ) as watcher:
                assert json.loads(watcher.receive_text()) == {
                    "type": "terminal_size", "cols": 170, "rows": 50}
                assert json.loads(pub.receive_text()) == {"type": "joined", "link_id": "l1"}
                pub.send_text(json.dumps(data_frame("l1", lookalike)))
                assert watcher.receive_bytes().decode() == lookalike
                pub.send_text(json.dumps({"type": "size", "link_id": "l1", "cols": 90,
                                          "rows": 30}))
                assert json.loads(watcher.receive_text())["cols"] == 90


def test_an_old_publisher_without_size_frames_still_streams():
    with relay() as (client, _factory):
        with publisher(client) as pub:
            pub.send_text(json.dumps(links_frame({"l1": SHARE_TOKEN})))
            wait_for_links(client, 1)
            with client.websocket_connect(
                "/watch/l1", subprotocols=watch_protocols(SHARE_TOKEN)
            ) as watcher:
                pub.send_text(json.dumps({"type": "size", "link_id": "l1", "cols": 0,
                                          "rows": 50}))
                pub.send_text(json.dumps(data_frame("l1", "plain output")))
                assert watcher.receive_bytes().decode() == "plain output"
            assert client.get("/healthz").json()["links"] == 1
