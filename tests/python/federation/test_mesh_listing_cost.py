
from __future__ import annotations

import asyncio
import dataclasses
import json
import sys
import time
import uuid
from contextlib import closing

import pytest

from tests.python.federation.test_peer_listing import Mac, macs  # noqa: F401

# ruff: noqa: E402
from src.core.bounded_stream import REASON_OVERFLOW, BoundedStream
from src.core.event_hub import MAX_EVENT_QUEUE_BYTES, EventHub
from src.core.federation import peer_event_stream, peer_listing, peer_listing_feed, peer_listing_push, shadow_rows
from src.core.federation.mesh_grants import MeshGrant
from src.core.federation.grants import Grant
from src.core.federation.peer_listing_feed import PeerListingFeed, row_key
from src.core.listing_push.diff import diff, keyed
from src.core.pack.machines import capabilities
from src.models import Session, SessionInfo, SessionStatus


def _wire(b: Mac, name: str, status: str = "idle", **over) -> dict:
    info = SessionInfo(session=Session(id=f"ses_B_{name}", working_dir=f"/work/{name}", status=SessionStatus.RUNNING), tmux_session=name, label=f"label {name}",
                       agent_type="claude", agent_family="claude", activity_status=status, session_uuid=str(uuid.uuid5(uuid.NAMESPACE_DNS, name)),
                       origin_install_id=b.install_id, host_key="local", session_row_id=7)
    row = info.model_dump(mode="json")
    row.update(over)
    return row


class Feed:

    def __init__(self, key=None) -> None:
        self.stream, self.seq, self.rows, self.asleep, self.key = "s1", -1, None, None, key or row_key

    def frame(self, rows: list, asleep: list | None = None, *, full: bool = False, order: bool = False) -> dict:
        self.seq += 1
        new, new_sleep = keyed(rows, self.key), keyed(asleep or [], self.key)
        out = {"type": "peer.listing", "stream": self.stream, "seq": self.seq, "full": full or self.rows is None,
               "list": diff(None if full or self.rows is None else self.rows, new), "asleep": diff(None if full or self.asleep is None else self.asleep, new_sleep)}
        self.rows, self.asleep = new, new_sleep
        return out


@pytest.fixture
def probe(macs, monkeypatch):
    a, b = macs
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    spies = {"ingest": 0, "sync": 0, "armed": False}
    real_ingest, real_sync = peer_listing.ingest, shadow_rows.sync_peer

    async def ingest(*args, **kw):
        spies["ingest"] += 1
        return await real_ingest(*args, **kw)

    def sync(*args, **kw):
        spies["sync"] += 1
        return real_sync(*args, **kw)

    def opener():
        if spies["armed"]:
            raise AssertionError("the fast path opened a datastore connection")
        return a.open_db()

    monkeypatch.setattr(peer_listing, "ingest", ingest)
    monkeypatch.setattr(shadow_rows, "sync_peer", sync)
    peer_listing_push._HELD.clear()
    peer_listing_push._REIMPORT_AT.clear()
    peer = next(p for p in peer_listing.read_peers(a.open_db) if p.peer_install_id == b.install_id)
    yield a, b, peer, spies, opener
    peer_listing_push._HELD.clear()
    peer_listing_push._REIMPORT_AT.clear()


def _start(probe, rows):
    a, b, peer, spies, opener = probe
    feed = Feed()
    assert asyncio.run(peer_listing_push.apply(feed.frame(rows), peer, opener)) is True
    spies["ingest"] = spies["sync"] = 0
    return feed


def _shown(peer):
    return {r.tmux_session: r for r in peer_listing.pushed_rows(peer.peer_install_id)}


def test_switch_off_a_status_delta_takes_the_import(probe, monkeypatch):
    a, b, peer, spies, opener = probe
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    rows = [_wire(b, "x"), _wire(b, "y")]
    feed = _start(probe, rows)
    assert asyncio.run(peer_listing_push.apply(feed.frame([_wire(b, "x", "working"), rows[1]]), peer, opener)) is True
    assert (spies["ingest"], spies["sync"]) == (1, 1)


def test_switch_on_a_status_delta_opens_no_connection_and_keeps_identity(probe):
    a, b, peer, spies, opener = probe
    rows = [_wire(b, "x"), _wire(b, "y")]
    feed = _start(probe, rows)
    before = _shown(peer)
    spies["armed"] = True
    assert asyncio.run(peer_listing_push.apply(feed.frame([_wire(b, "x", "working"), rows[1]]), peer, opener)) is True
    after = _shown(peer)
    assert (spies["ingest"], spies["sync"]) == (0, 0)
    assert after["x"].activity_status == "working" and after["y"] is before["y"]
    for field in ("session_row_id", "project_id", "project_name", "session_uuid"):
        assert getattr(after["x"], field) == getattr(before["x"], field)
    assert [r.tmux_session for r in peer_listing.pushed_rows(peer.peer_install_id)] == ["x", "y"] and peer.peer_install_id in peer_listing.PUSHED


@pytest.mark.parametrize("change", [{"label": "renamed"}, {"session": {"working_dir": "/elsewhere"}}])
def test_switch_on_a_label_or_folder_change_takes_the_import(probe, change):
    a, b, peer, spies, opener = probe
    feed = _start(probe, [_wire(b, "x")])
    row = _wire(b, "x")
    if "session" in change:
        row["session"] = {**row["session"], **change["session"]}
    else:
        row.update(change)
    assert asyncio.run(peer_listing_push.apply(feed.frame([row]), peer, opener)) is True
    assert spies["sync"] == 1 and spies["ingest"] == 1


def test_switch_on_an_add_a_remove_an_order_move_and_an_asleep_change_take_the_import(probe):
    a, b, peer, spies, opener = probe
    x, y = _wire(b, "x"), _wire(b, "y")
    feed = _start(probe, [x, y])
    steps = [lambda: feed.frame([x, y, _wire(b, "z")]),
             lambda: feed.frame([x, y]),
             lambda: feed.frame([y, x]),
             lambda: feed.frame([y, x], [_wire(b, "sleepy")])]
    for step in steps:
        spies["ingest"] = 0
        assert asyncio.run(peer_listing_push.apply(step(), peer, opener)) is True
        assert spies["ingest"] == 1


def test_switch_on_a_row_dropped_by_the_own_uuid_check_stays_dropped(probe):
    a, b, peer, spies, opener = probe
    own = str(next(iter(_own_uuid(a))))
    mine = _wire(b, "x", session_uuid=own)
    feed = _start(probe, [mine, _wire(b, "y")])
    assert [r.tmux_session for r in peer_listing.pushed_rows(peer.peer_install_id)] == ["y"]
    assert asyncio.run(peer_listing_push.apply(feed.frame([_wire(b, "x", "working", session_uuid=own), _wire(b, "y")]), peer, opener)) is True
    assert spies["ingest"] == 1 and [r.tmux_session for r in peer_listing.pushed_rows(peer.peer_install_id)] == ["y"]


def _own_uuid(a: Mac) -> list:
    with closing(a.open_db()) as conn:
        return [r[0] for r in conn.execute("SELECT session_uuid FROM sessions WHERE host_key = 'local' AND lifecycle = 'running'")]


@pytest.mark.parametrize("which", ["origin", "session_id"])
def test_switch_on_a_moved_origin_or_session_id_takes_the_import_and_is_refused(probe, which):
    a, b, peer, spies, opener = probe
    feed = _start(probe, [_wire(b, "x"), _wire(b, "y")])
    row = _wire(b, "x", "working")
    if which == "origin":
        row["origin_install_id"] = "someone-else"
    else:
        row["session"] = {**row["session"], "id": "remote:peer:x"}
    assert asyncio.run(peer_listing_push.apply(feed.frame([row, _wire(b, "y")]), peer, opener)) is True
    assert spies["ingest"] == 1 and [r.tmux_session for r in peer_listing.pushed_rows(peer.peer_install_id)] == ["y"]


def test_switch_on_a_row_failing_validation_takes_the_import_and_raises_nothing(probe):
    a, b, peer, spies, opener = probe
    feed = _start(probe, [_wire(b, "x"), _wire(b, "y")])
    assert asyncio.run(peer_listing_push.apply(feed.frame([_wire(b, "x", activity_status=None, unread="not a bool"), _wire(b, "y")]), peer, opener)) is True
    assert spies["ingest"] == 1 and "x" not in _shown(peer)


def test_a_full_frame_always_takes_the_import(probe):
    a, b, peer, spies, opener = probe
    rows = [_wire(b, "x"), _wire(b, "y")]
    feed = _start(probe, rows)
    assert asyncio.run(peer_listing_push.apply(feed.frame([_wire(b, "x", "working"), rows[1]], full=True), peer, opener)) is True
    assert (spies["ingest"], spies["sync"]) == (1, 1)



def test_a_due_deadline_sends_the_next_delta_through_the_import_and_renews_it(probe):
    a, b, peer, spies, opener = probe
    rows = [_wire(b, "x"), _wire(b, "y")]
    feed = _start(probe, rows)
    key = peer.peer_install_id
    assert _wire(b, "x") and peer_listing_push._REIMPORT_AT[key] > 0
    peer_listing_push._REIMPORT_AT[key] = 0
    assert asyncio.run(peer_listing_push.apply(feed.frame([_wire(b, "x", "working"), rows[1]]), peer, opener)) is True
    assert spies["ingest"] == 1 and peer_listing_push._REIMPORT_AT[key] > 0
    assert asyncio.run(peer_listing_push.apply(feed.frame([_wire(b, "x", "idle"), rows[1]]), peer, opener)) is True
    assert spies["ingest"] == 1


def test_a_local_project_rename_reaches_the_row_when_the_deadline_forces_the_import(probe):
    a, b, peer, spies, opener = probe
    rows = [_wire(b, "x"), _wire(b, "y")]
    feed = _start(probe, rows)
    old = _shown(peer)["x"]
    assert old.project_name and old.project_id is not None
    with closing(a.open_db()) as conn, conn:
        conn.execute("UPDATE projects SET display_name = 'renamed here' WHERE id = ?", (old.project_id,))
    assert asyncio.run(peer_listing_push.apply(feed.frame([_wire(b, "x", "working"), rows[1]]), peer, opener)) is True
    assert _shown(peer)["x"].project_name == old.project_name and spies["ingest"] == 0
    peer_listing_push._REIMPORT_AT[peer.peer_install_id] = 0
    assert asyncio.run(peer_listing_push.apply(feed.frame([_wire(b, "x", "idle"), rows[1]]), peer, opener)) is True
    assert _shown(peer)["x"].project_name == "renamed here" and spies["ingest"] == 1


def test_two_rows_sharing_one_session_uuid_take_the_import(probe):
    a, b, peer, spies, opener = probe
    same = str(uuid.uuid4())
    feed = Feed(key=lambda r: r["tmux_session"])
    assert asyncio.run(peer_listing_push.apply(feed.frame([_wire(b, "x", session_uuid=same), _wire(b, "y", session_uuid=same)]), peer, opener)) is True
    spies["ingest"] = 0
    assert asyncio.run(peer_listing_push.apply(feed.frame([_wire(b, "x", "working", session_uuid=same), _wire(b, "y", session_uuid=same)]), peer, opener)) is True
    assert spies["ingest"] == 1


def test_a_peer_label_change_takes_the_import_and_every_row_shows_it(probe):
    a, b, peer, spies, opener = probe
    rows = [_wire(b, "x"), _wire(b, "y")]
    feed = _start(probe, rows)
    relabeled = dataclasses.replace(peer, label="brand new label")
    assert asyncio.run(peer_listing_push.apply(feed.frame([_wire(b, "x", "working"), rows[1]]), relabeled, opener)) is True
    assert spies["ingest"] == 1 and {r.host_label for r in peer_listing.pushed_rows(peer.peer_install_id)} == {"brand new label"}


def _older_app(row: dict) -> dict:
    return {k: v for k, v in row.items() if k not in ("agent_family_source", "project_uid")}


def test_a_released_apps_frames_are_handled_exactly_as_the_full_import_handles_them(probe, monkeypatch):
    a, b, peer, spies, opener = probe
    made: dict = {}

    def w(name: str, status: str = "idle", **over) -> dict:
        return made.setdefault((name, status, tuple(sorted(over.items()))), _wire(b, name, status, **over))

    def sequence(feed):
        yield feed.frame([w("x"), w("y")], full=True)
        yield feed.frame([w("x", "working"), w("y")])
        yield feed.frame([w("x", "working", label="relabeled"), w("y")])
        yield feed.frame([w("x", "working", label="relabeled"), w("y"), w("z")])
        yield feed.frame([w("x", "working", label="relabeled"), w("z")])
        yield feed.frame([w("x", "idle", label="relabeled"), w("z", "working")])
        yield feed.frame([w("x", "idle", label="relabeled"), _older_app(w("z", "idle"))])

    def run(on: bool):
        monkeypatch.setattr(capabilities, "MESH_BUILD_ON", on)
        peer_listing.reset()
        peer_listing_push._HELD.clear()
        peer_listing_push._REIMPORT_AT.clear()
        with closing(a.open_db()) as conn, conn:
            shadow_rows.remove_peer(conn, peer.key)
            conn.execute("DELETE FROM sqlite_sequence WHERE name = 'projects'")
        spies["ingest"] = 0
        out, fast, feed = [], 0, Feed()
        for frame in sequence(feed):
            before = spies["ingest"]
            assert asyncio.run(peer_listing_push.apply(frame, peer, opener)) is True
            fast += spies["ingest"] == before and not frame["full"]
            with closing(a.open_db()) as conn:
                shadow = sorted(tuple(r) for r in conn.execute("SELECT session_uuid, project_id, working_dir, tmux_name FROM sessions WHERE host_key = ?", (peer.key,)))
            out.append(([r.model_dump() for r in peer_listing.pushed_rows(peer.peer_install_id)], shadow))
        return out, fast

    off, fast_off = run(False)
    on, fast_on = run(True)
    assert fast_off == 0 and fast_on >= 2
    for step, (got, want) in enumerate(zip(on, off)):
        for g, w_ in zip(got[0], want[0]):
            assert {k: (g[k], w_[k]) for k in g if g[k] != w_[k]} == {}, f"step {step}"
        assert got == want, f"step {step}"


def test_a_removed_peer_is_refused_and_drop_clears_the_held_rows_and_the_deadline(probe, monkeypatch):
    a, b, peer, spies, opener = probe
    feed = _start(probe, [_wire(b, "x")])
    key = peer.peer_install_id
    assert key in peer_listing_push._HELD and key in peer_listing_push._REIMPORT_AT
    monkeypatch.setattr(peer_listing, "read_peers", lambda *_a, **_k: [])
    with pytest.raises(peer_event_stream.PeerUnavailable):
        asyncio.run(peer_event_stream._apply_listing(feed.frame([_wire(b, "x", "working")]), key, opener))
    peer_listing_push.drop(key)
    assert key not in peer_listing_push._HELD and key not in peer_listing_push._REIMPORT_AT and key not in peer_listing.PUSHED


def _feed_of(rows: list, asleep: list | None = None) -> PeerListingFeed:
    async def view():
        return rows, asleep or []
    return PeerListingFeed(view)


def _fat(i: int, pad: int = 3000) -> dict:
    return {"session_uuid": f"u{i}", "tmux_session": f"t{i}", "pad": "x" * pad}


async def _queued(stream: BoundedStream) -> list:
    out = []
    while stream.queued_items:
        out.append(json.loads(await stream.get()))
    return out


def test_a_member_stream_takes_a_frame_a_default_stream_refuses():
    async def scenario():
        feed = _feed_of([_fat(i) for i in range(250)])
        plain = BoundedStream(max_items=64, max_bytes=1 << 20, label="plain")
        await feed.attach(plain)
        assert not feed._streams and plain.queued_items == 0
        member = BoundedStream(max_items=64, max_bytes=peer_listing_feed.MESH_QUEUE_BYTES, label="member")
        await feed.attach(member, cap=peer_listing_feed.frame_cap(True))
        assert member in feed._streams and len((await _queued(member))[0]["list"]["upsert"]) == 250
        feed.detach(member)
    asyncio.run(scenario())


def test_an_oversize_frame_resyncs_only_the_default_stream_and_a_star_only_feed_drops_all(monkeypatch):
    async def scenario():
        rows = [_fat(0, 0)]
        feed = _feed_of(rows)
        plain = BoundedStream(max_items=64, max_bytes=1 << 20, label="plain")
        member = BoundedStream(max_items=64, max_bytes=peer_listing_feed.MESH_QUEUE_BYTES, label="member")
        await feed.attach(plain)
        await feed.attach(member, cap=peer_listing_feed.frame_cap(True))
        await _queued(plain)
        await _queued(member)
        rows.extend(_fat(i) for i in range(1, 250))
        feed._wake.set()
        await asyncio.sleep(peer_listing_feed.COALESCE_SECONDS + 0.5)
        assert [f.get("resync") for f in await _queued(plain)] == [True] and plain not in feed._streams
        assert member in feed._streams and [f.get("full") for f in await _queued(member)] == [False]
        feed.detach(member)
        rows2 = [_fat(0, 0)]
        feed2 = _feed_of(rows2)
        a, b = (BoundedStream(max_items=64, max_bytes=1 << 20, label=n) for n in "ab")
        await feed2.attach(a)
        await feed2.attach(b)
        await _queued(a)
        await _queued(b)
        rows2.extend(_fat(i) for i in range(1, 250))
        feed2._wake.set()
        await asyncio.sleep(peer_listing_feed.COALESCE_SECONDS + 0.5)
        assert [f.get("resync") for f in await _queued(a)] == [True] == [f.get("resync") for f in await _queued(b)]
        assert not feed2._streams and feed2._list is None
    asyncio.run(scenario())


def test_a_member_stream_over_the_row_cap_gets_resync_and_never_a_501_row_frame():
    async def scenario():
        rows = [_fat(i, 0) for i in range(500)]
        feed = _feed_of(rows)
        member = BoundedStream(max_items=64, max_bytes=peer_listing_feed.MESH_QUEUE_BYTES, label="member")
        await feed.attach(member, cap=peer_listing_feed.frame_cap(True))
        assert len((await _queued(member))[0]["list"]["upsert"]) == 500
        rows.append(_fat(500, 0))
        feed._wake.set()
        await asyncio.sleep(peer_listing_feed.COALESCE_SECONDS + 0.5)
        frames = await _queued(member)
        assert [f.get("resync") for f in frames] == [True] and member not in feed._streams
        over = _feed_of([_fat(i, 0) for i in range(501)])
        late = BoundedStream(max_items=64, max_bytes=peer_listing_feed.MESH_QUEUE_BYTES, label="late")
        await over.attach(late, cap=peer_listing_feed.frame_cap(True))
        assert not over._streams and late.queued_items == 0
    asyncio.run(scenario())


def test_member_caps_only_for_a_mesh_grant_on_a_peer_socket_with_the_switch_on(monkeypatch):
    star = Grant("g", "iid", "k", "f", "l", ("sessions",), None, "t", None, None)
    mesh = MeshGrant("mesh-g", "iid", "k", "f", "l", (), None, "t", None, None)
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    assert peer_listing_feed.member_caps(True, mesh) == (4 * 1024 * 1024, 2 * 1024 * 1024)
    assert peer_listing_feed.member_caps(False, mesh) is None
    assert peer_listing_feed.member_caps(True, star) is None
    assert peer_listing_feed.member_caps(True, None) is None
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    assert peer_listing_feed.member_caps(True, mesh) is None


def test_a_member_stream_is_bounded_and_a_default_client_keeps_the_hub_bound():
    hub = EventHub()
    assert hub.register().stream.max_bytes == MAX_EVENT_QUEUE_BYTES
    client = hub.register(max_bytes=peer_listing_feed.MESH_QUEUE_BYTES)
    assert client.stream.max_bytes == peer_listing_feed.MESH_QUEUE_BYTES
    for _ in range(3):
        client.stream.offer("x" * 1_500_000, 1_500_000)
    assert client.stream.reason == REASON_OVERFLOW


def test_resync_wait_is_exactly_the_period_unless_the_switch_is_on_and_a_member_is_attached(monkeypatch):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    assert peer_listing_feed.resync_wait(True) == 60.0 == peer_listing_feed.resync_wait(False)
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    assert peer_listing_feed.resync_wait(False) == 60.0
    draws = [peer_listing_feed.resync_wait(True) for _ in range(20)]
    assert all(30.0 <= d <= 60.0 for d in draws) and len(set(draws)) > 1


def test_member_caps_checks_peer_and_the_switch_before_its_late_import(monkeypatch):
    monkeypatch.setitem(sys.modules, "src.core.federation.mesh_grants", None)
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    assert peer_listing_feed.member_caps(True, object()) is None
    assert peer_listing_feed.member_caps(False, object()) is None
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    assert peer_listing_feed.member_caps(False, object()) is None


def test_a_late_member_attach_is_not_dropped_by_an_oversize_default_frame(monkeypatch):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)

    async def scenario():
        feed = _feed_of([_fat(0, 0)])
        plain = BoundedStream(max_items=64, max_bytes=1 << 20, label="plain")
        member = BoundedStream(max_items=64, max_bytes=peer_listing_feed.MESH_QUEUE_BYTES, label="member")
        await feed.attach(plain)
        await feed.attach(member, cap=peer_listing_feed.frame_cap(True))
        await _queued(plain)
        await _queued(member)
        feed._send_sized("x" * (peer_listing_feed.frame_cap(False) + 1), [plain])
        assert member in feed._streams and member.queued_items == 0 and feed._list is not None
        assert [f.get("resync") for f in await _queued(plain)] == [True] and plain not in feed._streams
        feed.detach(member)
    asyncio.run(scenario())


def test_claim_is_one_per_owner_and_release_frees_it():
    feed = _feed_of([])
    assert feed.claim("a") and not feed.claim("a") and feed.claim("b")
    feed.release("a")
    feed.release("a")
    assert feed.claim("a") and not feed.claim("b")


def _member_socket_app(monkeypatch, on: bool):
    from fastapi import FastAPI

    from src.api import events_routes

    async def fake_try_peer(websocket):
        await websocket.accept(subprotocol="cloude.jwt.v1")
        gid = websocket.query_params.get("g", "g1")
        websocket.scope["peer_grant"] = MeshGrant(gid, websocket.query_params.get("i", gid), "k", "f", "l", (), None, "t", None, None)
        return True

    monkeypatch.setattr(events_routes.peer_ws_auth, "try_peer", fake_try_peer)
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", on)
    app = FastAPI()
    app.state.event_hub = EventHub()
    app.state.peer_listing_feed = _feed_of([_fat(i, 10) for i in range(3)])
    app.include_router(events_routes.router)
    return app


def _listing_frame(ws) -> dict:
    for _ in range(3):
        frame = json.loads(ws.receive_text())
        if frame.get("type") == "peer.listing":
            return frame
    raise AssertionError("no peer.listing frame")


def _wait_until(check, seconds: float = 3.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end and not check():
        time.sleep(0.05)
    return bool(check())


def test_one_listing_socket_per_member_grant_and_other_members_are_not_knocked_off(monkeypatch):
    from fastapi.testclient import TestClient

    app = _member_socket_app(monkeypatch, True)
    feed = app.state.peer_listing_feed
    with TestClient(app) as client:
        with client.websocket_connect("/ws/events?listing=push&g=g1") as one:
            assert _listing_frame(one)["full"] is True
            assert list(feed._streams.values()) == [peer_listing_feed.MESH_FRAME_BYTES]
            with client.websocket_connect("/ws/events?listing=push&g=g1") as two:
                json.loads(two.receive_text())
                time.sleep(0.4)
                assert len(feed._streams) == 1 and feed._owners == {"g1"}
                assert sorted(c.stream.max_bytes for c in app.state.event_hub._clients.values()) == [MAX_EVENT_QUEUE_BYTES, peer_listing_feed.MESH_QUEUE_BYTES]
            assert _wait_until(lambda: len(app.state.event_hub._clients) == 1)
            assert len(feed._streams) == 1 and feed._owners == {"g1"}
            with client.websocket_connect("/ws/events?listing=push&g=g2") as other:
                assert _listing_frame(other)["full"] is True
                assert len(feed._streams) == 2 and feed._owners == {"g1", "g2"}
        assert _wait_until(lambda: "g1" not in feed._owners)
        with client.websocket_connect("/ws/events?listing=push&g=g1") as three:
            assert _listing_frame(three)["full"] is True


def test_with_the_switch_off_no_listing_attachment_is_claimed(monkeypatch):
    from fastapi.testclient import TestClient

    app = _member_socket_app(monkeypatch, False)
    feed = app.state.peer_listing_feed
    with TestClient(app) as client, client.websocket_connect("/ws/events?listing=push&g=g1") as ws:
        assert _listing_frame(ws)["full"] is True
        assert feed._owners == set() and list(feed._streams.values()) == [None]


def test_a_cert_rotation_does_not_attach_a_second_listing_socket_for_one_computer(monkeypatch):
    from fastapi.testclient import TestClient

    app = _member_socket_app(monkeypatch, True)
    feed = app.state.peer_listing_feed
    with TestClient(app) as client:
        with client.websocket_connect("/ws/events?listing=push&g=old&i=computer-1") as one:
            assert _listing_frame(one)["full"] is True
            with client.websocket_connect("/ws/events?listing=push&g=new&i=computer-1") as two:
                json.loads(two.receive_text())
                time.sleep(0.4)
                assert len(feed._streams) == 1 and feed._owners == {"computer-1"}
        assert _wait_until(lambda: not feed._owners)
        with client.websocket_connect("/ws/events?listing=push&g=new&i=computer-1") as three:
            assert _listing_frame(three)["full"] is True


def test_a_socket_with_no_install_id_claims_and_attaches_nothing(monkeypatch):
    from fastapi.testclient import TestClient

    app = _member_socket_app(monkeypatch, True)
    feed = app.state.peer_listing_feed
    with TestClient(app) as client, client.websocket_connect("/ws/events?listing=push&g=g1&i=") as ws:
        assert json.loads(ws.receive_text())["type"] == "events.hello"
        time.sleep(0.3)
        assert feed._owners == set() and not feed._streams
