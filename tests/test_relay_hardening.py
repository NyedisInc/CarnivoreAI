
from __future__ import annotations

import asyncio
import json
import threading
import time
from contextlib import contextmanager
from typing import Callable, Iterator, List

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from structlog.testing import capture_logs

from relay.app import create_app
from relay.auth import publisher_token_ok, watch_token_ok
from relay.bounded import ENDED_CLOSE_CODE, REASON_ENDED, REFUSED_CLOSE_CODE
from relay.config import (
    DEFAULT_MAX_WATCHERS_PER_LINK,
    DEFAULT_MAX_WATCHERS_TOTAL,
    settings_from_env,
)
from relay.redaction import Redactor
from tests.relay_support import (
    RecordingFactory,
    StubRedactor,
    data_frame,
    links_frame,
    sha256_of,
    watch_protocols,
)
from tests.test_relay_hub import DIGEST_A, DIGEST_B, build_hub, declaration
from tests.test_relay_sockets import (
    SHARE_TOKEN,
    build_settings,
    publisher,
    relay,
    wait_for_links,
)

OTHER = "q" * 32


@contextmanager
def relay_with(factory: Callable[[], Redactor]) -> Iterator[TestClient]:
    with TestClient(create_app(build_settings(), redactor_factory=factory)) as client:
        yield client


def refusal_of(client, path: str, protocols: List[str]) -> WebSocketDisconnect:
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect(path, subprotocols=protocols):
            pass
    return refused.value




@pytest.mark.asyncio
async def test_a_second_publisher_cannot_take_over_a_live_link():
    hub = build_hub(RecordingFactory())
    hub.declare("pub_a", [declaration("l1", DIGEST_A)])
    watcher = hub.add_watcher("l1")
    with capture_logs() as logs:
        dropped = hub.declare("pub_b", [declaration("l1", DIGEST_B)])
    assert dropped == []
    assert watcher.stream.reason is None
    assert hub.digest_for("l1") == DIGEST_A
    assert await hub.publish("pub_b", "l1", "injected") is False
    assert await hub.publish("pub_a", "l1", "owner") is True
    refused = [e for e in logs if e["event"] == "relay_link_redeclare_refused"]
    assert len(refused) == 1
    assert set(refused[0]) == {"event", "log_level", "link_id"}
    assert refused[0]["link_id"] == "l1"
    for entry in logs:
        for value in entry.values():
            assert DIGEST_A[:8] not in str(value)
            assert DIGEST_B[:8] not in str(value)


def test_a_link_id_is_free_again_once_its_owner_disconnects():
    hub = build_hub(RecordingFactory())
    hub.declare("pub_a", [declaration("l1", DIGEST_A)])
    hub.declare("pub_b", [declaration("l1", DIGEST_B)])
    assert hub.digest_for("l1") == DIGEST_A
    hub.drop_publisher("pub_a")
    hub.declare("pub_b", [declaration("l1", DIGEST_B)])
    assert hub.digest_for("l1") == DIGEST_B


def test_a_takeover_attempt_leaves_the_owners_viewer_streaming():
    with relay() as (client, _factory):
        with publisher(client) as pub_a, publisher(client) as pub_b:
            pub_a.send_text(json.dumps(links_frame({"l1": SHARE_TOKEN})))
            wait_for_links(client, 1)
            with client.websocket_connect(
                "/watch/l1", subprotocols=watch_protocols(SHARE_TOKEN)
            ) as viewer:
                pub_b.send_text(json.dumps(links_frame({"l1": "attacker"}, publisher=OTHER)))
                pub_b.send_text(json.dumps(data_frame("l1", "from b")))
                pub_a.send_text(json.dumps(data_frame("l1", "from a")))
                assert viewer.receive_bytes().decode() == "from a"
            assert refusal_of(
                client, "/watch/l1", watch_protocols("attacker")
            ).code == REFUSED_CLOSE_CODE




def test_the_watcher_caps_default_to_16_per_link_and_512_total():
    defaults = settings_from_env({"RELAY_PUBLISH_TOKEN": "s"})
    assert defaults.max_watchers_per_link == DEFAULT_MAX_WATCHERS_PER_LINK == 16
    assert defaults.max_watchers_total == DEFAULT_MAX_WATCHERS_TOTAL == 512
    tuned = settings_from_env(
        {
            "RELAY_PUBLISH_TOKEN": "s",
            "RELAY_MAX_WATCHERS_PER_LINK": "3",
            "RELAY_MAX_WATCHERS_TOTAL": "7",
        }
    )
    assert (tuned.max_watchers_per_link, tuned.max_watchers_total) == (3, 7)


def test_the_hub_enforces_both_caps():
    hub = build_hub(RecordingFactory(), max_watchers_per_link=2, max_watchers_total=3)
    hub.declare("pub", [declaration("l1"), declaration("l2", DIGEST_B)])
    assert hub.add_watcher("l1") is not None
    assert hub.add_watcher("l1") is not None
    assert hub.add_watcher("l1") is None
    assert hub.watcher_refusal("l1") == "link_watcher_cap"
    assert hub.add_watcher("l2") is not None
    assert hub.add_watcher("l2") is None
    assert hub.watcher_refusal("l2") == "total_watcher_cap"
    assert hub.watcher_count("l1") == 2 and hub.watcher_count("l2") == 1


def test_a_capped_watcher_is_refused_exactly_like_a_wrong_token():
    with relay(build_settings(max_watchers_per_link=1)) as (client, _factory):
        with publisher(client) as pub:
            pub.send_text(json.dumps(links_frame({"l1": SHARE_TOKEN})))
            wait_for_links(client, 1)
            wrong = refusal_of(client, "/watch/l1", watch_protocols("nope"))
            with client.websocket_connect(
                "/watch/l1", subprotocols=watch_protocols(SHARE_TOKEN)
            ) as first:
                pub.send_text(json.dumps(data_frame("l1", "hi")))
                assert first.receive_bytes().decode() == "hi"
                with capture_logs() as logs:
                    capped = refusal_of(
                        client, "/watch/l1", watch_protocols(SHARE_TOKEN)
                    )
    assert capped.code == wrong.code == REFUSED_CLOSE_CODE
    assert capped.reason == wrong.reason
    reasons = [e.get("reason") for e in logs if e["event"] == "relay_watcher_refused"]
    assert reasons == ["link_watcher_cap"]




def test_non_ascii_credentials_compare_cleanly():
    assert publisher_token_ok("caf\xe9", "cafe") is False
    assert publisher_token_ok("caf\xe9", "caf\xe9") is True
    assert watch_token_ok("caf\xe9", sha256_of("cafe")) is False
    assert watch_token_ok("caf\xe9", None) is False


def test_a_non_ascii_bearer_is_refused_not_a_server_error():
    with relay() as (client, _factory):
        with pytest.raises(WebSocketDisconnect) as refused:
            with client.websocket_connect(
                "/publish", headers={b"authorization": b"Bearer caf\xe9"}
            ):
                pass
    assert refused.value.code == REFUSED_CLOSE_CODE


def test_a_non_ascii_share_token_is_refused_not_a_server_error():
    with relay() as (client, _factory):
        with publisher(client) as pub:
            pub.send_text(json.dumps(links_frame({"l1": SHARE_TOKEN})))
            wait_for_links(client, 1)
            with pytest.raises(WebSocketDisconnect) as refused:
                with client.websocket_connect(
                    "/watch/l1",
                    headers={
                        b"sec-websocket-protocol": b"cloude.relay.watch.v1, caf\xe9"
                    },
                ):
                    pass
    assert refused.value.code == REFUSED_CLOSE_CODE




class GatedRedactor(StubRedactor):

    def __init__(self, gate: threading.Event, hold: float) -> None:
        super().__init__()
        self._gate = gate
        self._hold = hold

    def feed(self, chunk: str) -> str:
        if "SLOW" in chunk:
            self._gate.wait(self._hold)
        return super().feed(chunk)


def test_a_busy_link_does_not_stall_another_links_watchers():
    gate = threading.Event()
    with relay_with(lambda: GatedRedactor(gate, 3.0)) as client:
        with publisher(client) as pub_a, publisher(client) as pub_b:
            pub_a.send_text(json.dumps(links_frame({"la": "tok-a"})))
            pub_b.send_text(json.dumps(links_frame({"lb": "tok-b"}, publisher=OTHER)))
            wait_for_links(client, 2)
            with client.websocket_connect(
                "/watch/la", subprotocols=watch_protocols("tok-a")
            ) as watch_a, client.websocket_connect(
                "/watch/lb", subprotocols=watch_protocols("tok-b")
            ) as watch_b:
                pub_a.send_text(json.dumps(data_frame("la", "SLOW scrub")))
                time.sleep(0.1)
                started = time.monotonic()
                pub_b.send_text(json.dumps(data_frame("lb", "fast")))
                assert watch_b.receive_bytes().decode() == "fast"
                assert client.get("/healthz").status_code == 200
                elapsed = time.monotonic() - started
                assert not gate.is_set()
                gate.set()
                assert watch_a.receive_bytes().decode() == "SLOW scrub"
    assert elapsed < 1.0, f"link B waited {elapsed:.2f}s behind link A"


class CountingRedactor(StubRedactor):

    def __init__(self) -> None:
        super().__init__()
        self._guard = threading.Lock()
        self._in_flight = 0
        self.max_in_flight = 0

    def _enter(self) -> None:
        with self._guard:
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
        time.sleep(0.02)

    def _leave(self) -> None:
        with self._guard:
            self._in_flight -= 1

    def feed(self, chunk: str) -> str:
        self._enter()
        try:
            return super().feed(chunk)
        finally:
            self._leave()

    def flush(self) -> str:
        self._enter()
        try:
            return super().flush()
        finally:
            self._leave()


@pytest.mark.asyncio
async def test_one_call_in_flight_per_link_and_order_is_kept():
    redactors: List[CountingRedactor] = []

    def factory() -> CountingRedactor:
        redactors.append(CountingRedactor())
        return redactors[-1]

    hub = build_hub(factory, idle_flush_ms=1)
    hub.declare("pub", [declaration("l1")])
    watcher = hub.add_watcher("l1")
    chunks = [f"c{i};" for i in range(8)]
    tasks = []
    for chunk in chunks:
        tasks.append(asyncio.create_task(hub.publish("pub", "l1", chunk)))
        await asyncio.sleep(0.005)
    assert all(await asyncio.gather(*tasks))
    (redactor,) = redactors
    deadline = time.monotonic() + 10.0
    while redactor.flush_calls < 1 and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    async with hub._links["l1"].scrub_lock:
        pass
    assert redactor.fed == chunks
    assert redactor.flush_calls >= 1
    assert redactor.max_in_flight == 1
    watcher.stream.close()
    received = []
    while (item := await watcher.stream.get()) is not None:
        received.append(item)
    assert "".join(received) == "".join(chunks)


class ExplodingRedactor(StubRedactor):

    def __init__(self, on: str) -> None:
        super().__init__(tail=4)
        self._on = on

    def feed(self, chunk: str) -> str:
        if self._on == "feed":
            raise RuntimeError("scrubber fault")
        return super().feed(chunk)

    def flush(self) -> str:
        if self._on == "flush":
            raise RuntimeError("scrubber fault")
        return super().flush()


def test_a_redactor_that_raises_on_feed_still_drops_the_publisher():
    with relay_with(lambda: ExplodingRedactor("feed")) as client:
        with pytest.raises(RuntimeError, match="scrubber fault"):
            with publisher(client) as pub:
                pub.send_text(json.dumps(links_frame({"l1": SHARE_TOKEN})))
                wait_for_links(client, 1)
                with client.websocket_connect(
                    "/watch/l1", subprotocols=watch_protocols(SHARE_TOKEN)
                ) as viewer:
                    assert client.get("/healthz").json()["publishers"] == 1
                    pub.send_text(json.dumps(data_frame("l1", "raw bytes")))
                    with pytest.raises(WebSocketDisconnect) as ended:
                        viewer.receive_bytes().decode()
                wait_for_links(client, 0)
                assert client.get("/healthz").json()["publishers"] == 0
    assert ended.value.code == ENDED_CLOSE_CODE


@pytest.mark.asyncio
async def test_a_redactor_that_raises_on_flush_ends_the_link():
    hub = build_hub(lambda: ExplodingRedactor("flush"), idle_flush_ms=1)
    hub.declare("pub", [declaration("l1")])
    watcher = hub.add_watcher("l1")
    assert await hub.publish("pub", "l1", "abcdefgh") is True
    assert await watcher.stream.get() == "abcd"
    await asyncio.sleep(0.2)
    assert watcher.stream.reason == REASON_ENDED
    assert await watcher.stream.get() is None
    assert hub.link_ids() == []




def test_an_abrupt_viewer_disconnect_at_close_logs_one_line(monkeypatch):
    from starlette.websockets import WebSocket as StarletteWebSocket

    real_close = StarletteWebSocket.close
    raised: List[str] = []

    async def vanished_close(self, code: int = 1000, reason=None) -> None:
        if self.url.path.startswith("/watch/"):
            raised.append(self.url.path)
            raise WebSocketDisconnect(code=1006)
        await real_close(self, code=code, reason=reason)

    monkeypatch.setattr(StarletteWebSocket, "close", vanished_close)
    with relay() as (client, _factory), capture_logs() as logs:
        with publisher(client) as pub:
            pub.send_text(json.dumps(links_frame({"l1": SHARE_TOKEN})))
            wait_for_links(client, 1)
            with client.websocket_connect(
                "/watch/l1", subprotocols=watch_protocols(SHARE_TOKEN)
            ) as viewer:
                pub.send_text(json.dumps(links_frame({})))
                wait_for_links(client, 0)
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline and not any(
                    e["event"] == "relay_watcher_close_noop" for e in logs
                ):
                    time.sleep(0.01)
                viewer.close()
    assert raised == ["/watch/l1"]
    noop = [e for e in logs if e["event"] == "relay_watcher_close_noop"]
    assert [e["error"] for e in noop] == ["WebSocketDisconnect"]
