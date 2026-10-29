
from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest

from tests.python.federation.test_peer_listing import Mac, _Client, macs  # noqa: F401
from tests.python.federation.test_peer_notifications import peer_bearer  # noqa: F401

# ruff: noqa: E402
from src.core.bounded_stream import BoundedStream
from src.core.federation import peer_event_stream, peer_events, peer_hosts, peer_links, peer_listing, peer_listing_push, peer_serve
from src.core.federation.peer_listing_feed import PeerListingFeed
from src.core.listing_push.diff import apply_change, diff, keyed


def _feed(mac: Mac) -> PeerListingFeed:
    async def view():
        served = await mac.list_body(as_peer=True)
        return [i.model_dump(mode="json") for i in served], peer_serve.serve_asleep_to_peer(mac.open_db)
    return PeerListingFeed(view)


def _peer_row(a: Mac, b: Mac):
    return next(p for p in peer_listing.read_peers(a.open_db) if p.peer_install_id == b.install_id)


async def _frame(stream: BoundedStream) -> dict:
    return json.loads(await asyncio.wait_for(stream.get(), 1))


def test_diff_apply_is_the_inverse_of_diff():
    old = keyed([{"k": "a", "x": 1, "n": {"p": 1, "q": 1}}, {"k": "b", "x": 2}], lambda r: r["k"])
    new = keyed([{"k": "c", "x": 3}, {"k": "a", "x": 5, "n": {"p": 2, "q": 1}}], lambda r: r["k"])
    assert apply_change(old, diff(old, new)) == new
    assert apply_change(None, diff(None, new)) == new


def test_peer_gets_only_owned_rows_and_applies_deltas_without_fetching(macs, monkeypatch):
    a, b = macs
    asyncio.run(a.list_body(as_peer=False))
    b.own[0] = b.own[0].model_copy(update={"project_name": "owner-only", "session": b.own[0].session.model_copy(update={"pty_pid": 4242})})
    asyncio.run(b.list_body(as_peer=False))
    from tests.python.federation.test_peer_listing import _dirty
    _dirty(b)
    requests = []
    real = _Client.request

    async def counting(self, method, path, **kw):
        requests.append(path)
        return await real(self, method, path, **kw)

    monkeypatch.setattr(_Client, "request", counting)

    async def scenario():
        feed, stream = _feed(b), BoundedStream(max_items=64, max_bytes=1 << 22, label="peer")
        await feed.attach(stream)
        full = await _frame(stream)
        text = json.dumps(full)
        assert full["full"] is True and "remote:" not in text and "owner-only" not in text and "4242" not in text
        assert [u["fields"]["tmux_session"] for u in full["list"]["upsert"]] == ["bravo"]
        peer = _peer_row(a, b)
        assert await peer_listing_push.apply(full, peer, a.open_db) is True
        assert peer.peer_install_id in peer_listing.PUSHED
        monkeypatch.setattr(peer_listing, "FRESH_SECONDS", 0.0)
        monkeypatch.setattr(peer_listing, "STALE_SECONDS", 0.0)
        before = len(requests)
        shown = await peer_listing.peer_rows(a.open_db)
        assert len(requests) == before and sorted(r.tmux_session for r in shown if r.host_key != "local") == ["bravo"]
        assert all(r.host_state == "up" for r in shown if r.host_key != "local")
        b.add_session("charlie")
        feed._wake.set()
        sent = await feed._refresh()
        assert sent is not None and sent["full"] is False and sent["seq"] == full["seq"] + 1
        assert await peer_listing_push.apply(sent, peer, a.open_db) is True
        shown = await peer_listing.peer_rows(a.open_db)
        assert sorted(r.tmux_session for r in shown if r.host_key != "local") == ["bravo", "charlie"]
        assert len(requests) == before
        gap = {**sent, "seq": sent["seq"] + 2}
        assert await peer_listing_push.apply(gap, peer, a.open_db) is False
        peer_listing_push.drop(peer.peer_install_id)
        await peer_listing.peer_rows(a.open_db)
        assert len(requests) > before
        feed.detach(stream)

    class _Links:
        def client(self, _id):
            return _Client(b)

        def state(self, _id):
            return "connected"

    monkeypatch.setattr(peer_links, "LINKS", _Links())
    asyncio.run(scenario())


def test_peer_events_makes_no_fetch_while_pushed_and_polls_otherwise(macs, monkeypatch):
    a, b = macs
    asyncio.run(a.list_body(as_peer=False))
    requests = []
    real = _Client.request

    async def counting(self, method, path, **kw):
        requests.append(path)
        return await real(self, method, path, **kw)

    class _Links:
        def client(self, _id):
            return _Client(b)

        def state(self, _id):
            return "connected"

    monkeypatch.setattr(_Client, "request", counting)
    monkeypatch.setattr(peer_links, "LINKS", _Links())
    monkeypatch.setattr(peer_event_stream, "sync", lambda *_a: None)
    monkeypatch.setattr(peer_listing, "FRESH_SECONDS", 0.0)

    async def follow(seconds):
        task = asyncio.create_task(peer_events.run(object(), a.open_db, interval=0.01))
        await asyncio.sleep(seconds)
        task.cancel()

    peer_listing.PUSHED.add(b.install_id)
    asyncio.run(follow(0.3))
    assert requests == []
    peer_listing.PUSHED.discard(b.install_id)
    asyncio.run(follow(0.3))
    assert any(p.startswith("/sessions/") for p in requests)


def _wide_feed(rows: list) -> PeerListingFeed:
    async def view():
        return rows, []
    return PeerListingFeed(view)


def _row(i: int, pad: int = 0) -> dict:
    return {"session_uuid": f"u{i}", "tmux_session": f"t{i}", "pad": "x" * pad}


def test_a_view_too_big_for_one_frame_attaches_nothing_and_a_growing_one_sends_resync(monkeypatch) -> None:
    monkeypatch.setattr("src.core.federation.peer_listing_feed.MAX_FRAME_BYTES", 4000)

    async def scenario():
        big = _wide_feed([_row(i, 200) for i in range(40)])
        stream = BoundedStream(max_items=64, max_bytes=1 << 20, label="peer")
        await big.attach(stream)
        assert not big._streams and stream.queued_items == 0
        rows = [_row(0)]
        feed = _wide_feed(rows)
        stream = BoundedStream(max_items=64, max_bytes=1 << 20, label="peer")
        await feed.attach(stream)
        assert (await _frame(stream))["full"] is True
        rows.extend(_row(i, 200) for i in range(1, 40))
        feed._wake.set()
        task = feed._task
        sent = await asyncio.wait_for(_frame(stream), 3)
        assert sent.get("resync") is True and not feed._streams
        return sent, task

    sent, task = asyncio.run(scenario())
    key = "iid-x"
    peer_listing.PUSHED.add(key)
    peer = type("P", (), {"peer_install_id": key, "key": "peer-x"})()
    assert asyncio.run(peer_listing_push.apply(sent, peer, None)) is True
    assert key not in peer_listing.PUSHED


def test_a_full_frame_is_resent_while_the_socket_lives_and_the_wake_comes_from_the_hub(monkeypatch) -> None:
    monkeypatch.setattr("src.core.federation.peer_listing_feed.RESYNC_SECONDS", 0.05)

    async def scenario():
        rows = [_row(0)]
        feed = _wide_feed(rows)
        stream = BoundedStream(max_items=64, max_bytes=1 << 20, label="peer")
        feed.on_hub_publish("listing.delta")
        assert not feed._wake.is_set()
        await feed.attach(stream)
        first = await _frame(stream)
        rows.append(_row(1))
        second = await asyncio.wait_for(_frame(stream), 2)
        assert second["full"] is True and len(second["list"]["upsert"]) == 2 and second["seq"] >= first["seq"]
        feed.on_hub_publish("preferences.changed")
        assert not feed._wake.is_set()
        feed.on_hub_publish("listing.delta")
        assert feed._wake.is_set()
        feed.detach(stream)

    asyncio.run(scenario())


def test_an_in_flight_poll_never_overwrites_a_newer_pushed_snapshot(macs, monkeypatch) -> None:
    a, b = macs
    asyncio.run(a.list_body(as_peer=False))
    real = _Client.request
    started, release = None, None

    async def slow(self, method, path, **kw):
        response = await real(self, method, path, **kw)
        started.set()
        await release.wait()
        return response

    class _Links:
        def client(self, _id):
            return _Client(b)

        def state(self, _id):
            return "connected"

    monkeypatch.setattr(_Client, "request", slow)
    monkeypatch.setattr(peer_links, "LINKS", _Links())

    async def scenario():
        nonlocal started, release
        started, release = asyncio.Event(), asyncio.Event()
        peer = _peer_row(a, b)
        poll = asyncio.create_task(peer_listing.refresh(peer, _Links(), a.open_db, force=True))
        await started.wait()
        b.add_session("charlie")
        feed, stream = _feed(b), BoundedStream(max_items=64, max_bytes=1 << 22, label="peer")
        await feed.attach(stream)
        assert await peer_listing_push.apply(await _frame(stream), peer, a.open_db) is True
        release.set()
        await poll
        feed.detach(stream)
        return peer_listing._SNAPSHOTS[peer.peer_install_id]

    snap = asyncio.run(scenario())
    assert sorted(r.tmux_session for r in snap.rows) == ["bravo", "charlie"]


def test_the_events_socket_feeds_only_a_peer_that_asked_and_detaches_on_close(peer_bearer, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from src.core import event_hub
    from src.main import app

    monkeypatch.setattr("src.core.federation.peer_listing_feed.RESYNC_SECONDS", 0.1)
    rows = [_row(0)]
    feed = _wide_feed(rows)
    monkeypatch.setattr(app.state, "event_hub", event_hub.EventHub(), raising=False)
    monkeypatch.setattr(app.state, "peer_listing_feed", feed, raising=False)
    client = TestClient(app, raise_server_exceptions=False)
    protocols = ["cloude.jwt.v1", peer_bearer]
    with client.websocket_connect("/ws/events", subprotocols=protocols) as ws:
        assert json.loads(ws.receive_text())["type"] == "events.hello"
        app.state.event_hub.publish({"type": "toast.new", "toast": {"id": "t", "session_id": "ses_1", "kind": "k"}})
        assert json.loads(ws.receive_text())["type"] == "toast.new"
    assert not feed._streams
    with client.websocket_connect("/ws/events?listing=push", subprotocols=protocols) as ws:
        assert json.loads(ws.receive_text())["type"] == "events.hello"
        first = json.loads(ws.receive_text())
        assert first["type"] == "peer.listing" and first["full"] is True and len(feed._streams) == 1
        rows.append(_row(1))
        while True:
            frame = json.loads(ws.receive_text())
            if frame["type"] == "peer.listing" and len(frame["list"]["upsert"]) == 2:
                break
    assert not feed._streams


class _GatedJson:

    def __init__(self, sleep: float = 0.0) -> None:
        self.entered, self.release, self.sleep = threading.Event(), threading.Event(), sleep

    def dumps(self, obj):
        if obj.get("full") is False:
            self.entered.set()
            if self.sleep:
                time.sleep(self.sleep)
            else:
                assert self.release.wait(5)
        return json.dumps(obj)


def test_a_socket_attached_while_a_delta_is_serialised_never_gets_that_delta_again(monkeypatch) -> None:
    monkeypatch.setattr("src.core.federation.peer_listing_feed.COALESCE_SECONDS", 0)
    gate = _GatedJson()
    monkeypatch.setattr("src.core.federation.peer_listing_feed.json", gate)

    async def scenario():
        rows = [_row(0)]
        feed = _wide_feed(rows)
        first = BoundedStream(max_items=64, max_bytes=1 << 20, label="peer")
        await feed.attach(first)
        await _frame(first)
        rows.append(_row(1))
        feed._wake.set()
        assert await asyncio.to_thread(gate.entered.wait, 5)
        late = BoundedStream(max_items=64, max_bytes=1 << 20, label="peer")
        attach = asyncio.ensure_future(feed.attach(late))
        await asyncio.sleep(0.2)
        gate.release.set()
        await attach
        full = await _frame(late)
        delta = await _frame(first)
        await asyncio.sleep(0.3)
        feed.detach(first)
        feed.detach(late)
        return full, delta, late.queued_items

    full, delta, late_left = asyncio.run(scenario())
    assert full["full"] is True and len(full["list"]["upsert"]) == 2 and delta["full"] is False and delta["seq"] == full["seq"]
    assert late_left == 0


def _ticks_while(feed_setup, monkeypatch) -> int:
    monkeypatch.setattr("src.core.federation.peer_listing_feed.COALESCE_SECONDS", 0)

    async def scenario():
        rows = [_row(0)]
        feed = _wide_feed(rows)
        feed_setup(feed)
        stream = BoundedStream(max_items=64, max_bytes=1 << 20, label="peer")
        await feed.attach(stream)
        await _frame(stream)
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        task = asyncio.ensure_future(ticker())
        rows.append(_row(1))
        feed._wake.set()
        assert (await _frame(stream))["full"] is False
        task.cancel()
        feed.detach(stream)
        return ticks

    return asyncio.run(scenario())


def test_the_feed_diffs_and_serialises_off_the_loop(monkeypatch) -> None:
    real = PeerListingFeed._compute

    def slow_compute(*args):
        time.sleep(0.4)
        return real(*args)

    assert _ticks_while(lambda f: setattr(f, "_compute", slow_compute), monkeypatch) >= 20
    monkeypatch.setattr("src.core.federation.peer_listing_feed.json", _GatedJson(sleep=0.4))
    assert _ticks_while(lambda f: None, monkeypatch) >= 20


def test_a_cancelled_attach_still_unregisters_the_stream(peer_bearer, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from src.core import event_hub
    from src.main import app

    started, detached = threading.Event(), []

    class Hung(PeerListingFeed):
        async def attach(self, stream):
            started.set()
            raise asyncio.CancelledError

        def detach(self, stream):
            detached.append(stream)

    hub = event_hub.EventHub()
    monkeypatch.setattr(app.state, "event_hub", hub, raising=False)
    monkeypatch.setattr(app.state, "peer_listing_feed", Hung(lambda: None), raising=False)
    client = TestClient(app, raise_server_exceptions=False)
    with pytest.raises(BaseException):
        with client.websocket_connect("/ws/events?listing=push", subprotocols=["cloude.jwt.v1", peer_bearer]):
            assert started.wait(5)
    assert len(detached) == 1
    assert not hub._clients
