
from __future__ import annotations

import asyncio
import json
from contextlib import closing

import pytest

from src.api import peer_auth
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.federation import peer_fanout, peer_hosts
from src.core.stats import config
from src.core.stats_feed import peers
from tests.python.federation.test_federation_route_inventory import peer_bearer  # noqa: F401
from tests.python.stats_feed.conftest import NOW, env, line  # noqa: F401

_REAL_ASK = peer_fanout.ask_peers
STUDIO_ID = "iid-studio"
STUDIO_KEY = peer_hosts.host_key_for(STUDIO_ID)
LAST_1H = NOW // 60 * 60
BAD = 1234567


@pytest.fixture
def paired(tmp_path, monkeypatch):
    ensure_db_migrated(tmp_path)
    path = db_path_for(tmp_path)
    monkeypatch.setattr(peer_auth, "open_db", lambda: connect(path, create=False))
    with closing(connect(path, create=False)) as conn:
        peer_hosts.upsert(conn, install_id=STUDIO_ID, label="studio", grant_id="g", fid="f", initiator=True)
    box = {"reply": [], "asked": []}

    async def fake(path, open_db, links=None):
        box["asked"].append(path)
        return box["reply"]

    monkeypatch.setattr(peer_fanout, "ask_peers", fake)
    return box


def wire(*, now=NOW, state="ok", rev=7, through=None, rate=True, buckets=None, install=STUDIO_ID, **more) -> dict:
    return {"v": 1, "install_id": install, "rev": rev, "now": now, "state": state, "data_through": through,
            "rate": rate if isinstance(rate, dict) else (
                {"span_seconds": 280.0, "fresh": 1.0, "cache_write": 2.0, "cache_read": 3.0, "out": 4.0} if rate else None),
            "windows": {"1h": buckets if buckets is not None else [[LAST_1H, 10, 20, BAD, 40]], "5h": [], "1d": [], "7d": []},
            "gaps": [], **more}


def up(data: dict) -> list:
    return [peer_fanout.PeerAnswer(STUDIO_KEY, "studio", data)]


def down(reason: str) -> list:
    return [peer_fanout.PeerAnswer(STUDIO_KEY, "studio", None, reason)]


def doc(feed, wall) -> dict:
    return json.loads(asyncio.run(feed.body("1h", lease=False)))


def source(document: dict, key: str) -> dict:
    return next(s for s in document["sources"] if s["host_key"] == key)


def test_merge_names_a_down_peer_and_never_reexports(env, paired):
    env.deliver([line(NOW - 30, "a", fresh=4, write=5, read=6, out=7)])
    wall = [NOW]
    feed = env.feed(wall=lambda: wall[0])
    paired["reply"] = up(wire())
    merged = doc(feed, wall)
    assert merged["totals"] == {"fresh": 14, "cache_write": 25, "cache_read": 6 + BAD, "out": 47}
    assert merged["state"] == "ok" and source(merged, STUDIO_KEY)["state"] == "ok"
    assert merged["rate"]["out"] == round(feed._measured("1h", NOW)[1]["out"] + 4.0, 1)

    served = asyncio.run(feed.local_answer())
    rows = [b for window in served["windows"].values() for b in window]
    assert rows and sum(b[3] for b in served["windows"]["1h"]) == 6 and str(BAD) not in json.dumps(served)

    paired["reply"] = down("timeout")
    assert asyncio.run(peers.pull_once(feed)) is True
    wall[0] = NOW + 300
    gone = doc(feed, wall)
    studio = source(gone, STUDIO_KEY)
    assert gone["state"] == "partial" and studio["state"] == "unreachable" and studio["reason"] == "timeout"
    assert studio["totals"]["cache_read"] == BAD
    assert gone["rate"]["out"] == feed._measured("1h", wall[0])[1]["out"]

    config.update_settings(env.store, enabled=False, revision=config.get_settings(env.store)["revision"])
    asyncio.run(feed.refresh())
    off = doc(feed, wall)
    assert off["state"] == "stats_off"
    held = [i for i, v in enumerate(off["in"]) if v is not None]
    assert off["in"][held[-1]] == 10 + 20 + BAD and held[-1] < len(off["in"]) - 1
    assert off["in"][held[-1] + 1:] == [None] * (len(off["in"]) - held[-1] - 1)


def test_t13b_an_ok_answer_from_before_an_idle_gap_is_not_live(env, paired):
    env.deliver([line(NOW - 30, "a", fresh=4, write=5, read=6, out=7)])
    wall = [NOW]
    feed = env.feed(wall=lambda: wall[0], clock=lambda: env.clock[0])
    paired["reply"] = up(wire())
    assert asyncio.run(peers.pull_once(feed)) is True
    asyncio.run(feed.refresh())
    own_out = feed._measured("1h", NOW)[1]["out"]
    assert json.loads(feed._served("1h"))["rate"]["out"] == own_out + 4.0
    for later, counted in ((60.0, True), (7200.0, False)):
        env.clock[0], wall[0] = later, NOW + later
        served = json.loads(feed._served("1h"))
        studio = source(served, STUDIO_KEY)
        assert served["state"] == "partial" and studio["state"] == "unreachable" and studio["reason"] == "stale"
        assert served["rate"]["out"] == feed._measured("1h", wall[0])[1]["out"]
        assert (studio["totals"] is not None) is counted
        if counted:
            assert studio["totals"]["cache_read"] == BAD
        else:
            own = feed._measured("1h", wall[0])[0]
            assert served["in"] == [None if b is None else b.tokens_in for b in own]


def test_a_lease_read_after_idle_asks_the_peers_before_serving(env, paired):
    env.deliver([line(NOW - 30, "a", fresh=4, write=5, read=6, out=7)])

    async def go():
        feed = env.feed()
        paired["reply"] = up(wire())
        merged = json.loads(await feed.body("1h"))
        assert source(merged, STUDIO_KEY)["state"] == "ok" and len(paired["asked"]) == 1
        await feed.stop()

    asyncio.run(go())


def test_two_concurrent_first_reads_share_one_ask_and_both_name_the_peer(env, paired):
    env.deliver([line(NOW - 30, "a", fresh=4, write=5, read=6, out=7)])

    async def go():
        feed = env.feed()
        gate = asyncio.Event()
        original = peer_fanout.ask_peers

        async def slow(path, open_db, links=None):
            paired["asked"].append(path)
            await gate.wait()
            return up(wire())

        peer_fanout.ask_peers = slow
        try:
            first = asyncio.ensure_future(feed.body("1h"))
            await asyncio.sleep(0.05)
            second = asyncio.ensure_future(feed.body("1h"))
            await asyncio.sleep(0.05)
            gate.set()
            docs = [json.loads(b) for b in await asyncio.gather(first, second)]
        finally:
            peer_fanout.ask_peers = original
        await feed.stop()
        return docs

    docs = asyncio.run(go())
    assert len(paired["asked"]) == 1
    assert all(source(d, STUDIO_KEY)["state"] == "ok" for d in docs)


def test_a_one_shot_read_loop_asks_the_peers_at_most_once_per_pull_interval(env, paired):
    env.deliver([line(NOW - 30, "a", fresh=4, write=5, read=6, out=7)])

    async def go():
        feed = env.feed()
        paired["reply"] = up(wire())
        for _ in range(4):
            await feed.body("1h", lease=False)

    asyncio.run(go())
    assert len(paired["asked"]) == 1


def test_could_not_ask_keeps_the_peers_named_and_no_peers_empties_the_book(env, paired, monkeypatch):
    env.deliver([line(NOW - 30, "a", fresh=4, write=5, read=6, out=7)])
    feed = env.feed()
    paired["reply"] = up(wire())
    asyncio.run(peers.pull_once(feed))
    paired["reply"] = []
    asyncio.run(peers.pull_once(feed))
    assert feed.peer_book.items[STUDIO_KEY].reason == "not_asked"

    def boom():
        raise OSError("disk")

    monkeypatch.setattr(peer_auth, "open_db", boom)
    asyncio.run(peers.pull_once(feed))
    assert feed.peer_book.items[STUDIO_KEY].reason == "local_unreadable"
    assert feed.peer_book.items[STUDIO_KEY].answer is not None

    monkeypatch.setattr(peers, "_pinned", lambda open_db: {})
    monkeypatch.setattr(peer_auth, "open_db", lambda: None)
    assert asyncio.run(peers.pull_once(feed)) is True and feed.peer_book.items == {}


def test_old_build_is_not_supported_and_not_counted(env, paired):
    env.deliver([line(NOW - 30, "a", fresh=4, write=5, read=6, out=7)])
    feed = env.feed()
    paired["reply"] = down("http_404")
    merged = doc(feed, [NOW])
    assert source(merged, STUDIO_KEY)["state"] == "not_supported" and source(merged, STUDIO_KEY)["totals"] is None
    assert merged["state"] == "partial" and merged["totals"] == {"fresh": 4, "cache_write": 5, "cache_read": 6, "out": 7}
    paired["reply"] = down("http_403")
    env.clock[0] += peers.PULL_S + 1
    assert doc(feed, [NOW])["sources"][1]["state"] == "refused"


def test_a_peer_silent_for_an_hour_is_listed_and_contributes_nothing(env, paired):
    env.deliver([line(NOW - 30, "a", fresh=4, write=5, read=6, out=7)])
    feed = env.feed(clock=lambda: env.clock[0])
    paired["reply"] = up(wire())
    assert source(doc(feed, [NOW]), STUDIO_KEY)["totals"] is not None
    paired["reply"] = down("unreachable")
    env.clock[0] = peers.STALE_S + 1
    merged = doc(feed, [NOW])
    assert source(merged, STUDIO_KEY)["totals"] is None and merged["totals"]["cache_read"] == 6


def test_skew_is_flagged_but_merging_stays_by_absolute_bucket(env, paired):
    env.deliver([line(NOW - 30, "a", fresh=4, write=5, read=6, out=7)])
    wall = [NOW]
    feed = env.feed(wall=lambda: wall[0])
    paired["reply"] = up(wire(now=NOW + 47, buckets=[[LAST_1H + 60, 1, 1, 1, 1]]))
    merged = doc(feed, wall)
    studio = source(merged, STUDIO_KEY)
    assert studio["skew_seconds"] == 47.0 and studio["skewed"] is False
    assert merged["in"][-1] == 4 + 5 + 6 + 3 and merged["totals"]["out"] == 8
    paired["reply"] = up(wire(now=NOW + 400, rev=8))
    asyncio.run(peers.pull_once(feed))
    wall[0] = NOW + 1
    assert source(doc(feed, wall), STUDIO_KEY)["skewed"] is True


@pytest.mark.parametrize("bad", [
    {"install": "iid-someone-else"},
    {"extra": {"another_computer": {}}},
    {"v": 2},
    {"rate": {"span_seconds": 1, "fresh": -1, "cache_write": 0, "cache_read": 0, "out": 0}},
    {"buckets": [[LAST_1H - 60 * i, 1, 1, 1, 1] for i in range(61)]},
    {"buckets": [[LAST_1H, 10**14, 0, 0, 0]]},
])
def test_loop_guard_import_refuses_what_it_should_not_trust(env, paired, bad):
    env.deliver([line(NOW - 30, "a", fresh=4, write=5, read=6, out=7)])
    feed = env.feed()
    data = wire(**{k: v for k, v in bad.items() if k not in ("extra", "v")})
    if "extra" in bad:
        data.update(bad["extra"])
    if "v" in bad:
        data["v"] = bad["v"]
    paired["reply"] = up(data)
    merged = doc(feed, [NOW])
    assert source(merged, STUDIO_KEY)["state"] == "refused" and source(merged, STUDIO_KEY)["totals"] is None
    assert merged["totals"]["cache_read"] == 6


def test_loop_guard_a_peer_lease_never_starts_the_pull(env, paired):
    async def go():
        feed = env.feed()
        feed.touch_peer()
        await asyncio.sleep(0.05)
        assert feed.leased() and feed.running and not feed.owner_leased()
        assert feed._pull_task is None and paired["asked"] == []
        await feed.stop()

    asyncio.run(go())


def test_loop_guard_the_owner_lease_pulls_while_it_lives_and_names_the_topic(env, paired):
    async def go():
        ticks = []

        async def sleep(seconds):
            ticks.append(seconds)
            await asyncio.sleep(0)
            if len(ticks) > 8:
                feed._lease_until = 0.0

        feed = env.feed(sleep=sleep)
        paired["reply"] = up(wire())
        await feed.body("1h")
        await asyncio.wait_for(feed._pull_task, 2)
        assert len(paired["asked"]) >= 2 and paired["asked"][0] == "/stats/feed/local"
        assert ("stats_feed", "local", 1.0) in env.notified
        await feed.stop()

    asyncio.run(go())


def test_loop_guard_the_owner_route_refuses_a_peer_token_and_the_peer_route_takes_it(env, paired, peer_bearer, monkeypatch):  # noqa: F811
    from fastapi.testclient import TestClient

    from src.main import app

    env.deliver([line(NOW - 30, "a", fresh=4, write=5, read=6, out=7)])
    feed = env.feed()
    monkeypatch.setattr(app.state, "stats_feed", feed, raising=False)
    client = TestClient(app, raise_server_exceptions=False)
    head = {"Authorization": f"Bearer {peer_bearer}"}
    assert client.get("/api/v1/stats/feed", headers=head).status_code == 401
    served = client.get("/api/v1/stats/feed/local", headers=head)
    assert served.status_code == 200, served.text
    assert served.json()["install_id"] and "sources" not in served.json()
    assert client.get("/api/v1/stats/feed/local").status_code == 401


def test_t16_the_peer_route_is_on_the_inventory_with_scope_sessions():
    from tests.python.federation.test_federation_route_inventory import PEER_ALLOWED

    assert PEER_ALLOWED[("GET", "/api/v1/stats/feed/local")] == "sessions"


def test_a_paired_computer_that_was_never_asked_is_still_named(env, paired, monkeypatch):
    from unittest.mock import MagicMock

    from src.core.computers import direction
    from src.core.federation import peer_links

    env.deliver([line(NOW - 30, "a", fresh=4, write=5, read=6, out=7)])
    monkeypatch.setattr(peer_fanout, "ask_peers", _REAL_ASK)

    monkeypatch.setattr(peer_links, "LINKS", None)
    feed = env.feed()
    merged = doc(feed, [NOW])
    studio = source(merged, STUDIO_KEY)
    assert studio["label"] == "studio" and studio["state"] == "unreachable" and studio["reason"] == "not_asked"
    assert merged["state"] == "partial" and studio["totals"] is None

    monkeypatch.setattr(peer_links, "LINKS", MagicMock())
    monkeypatch.setattr(direction, "is_one_way_toward", lambda install_id: install_id == STUDIO_ID)
    feed = env.feed()
    studio = source(doc(feed, [NOW]), STUDIO_KEY)
    assert studio["state"] == "unreachable" and studio["reason"] == "not_asked"


def test_loop_guard_local_answer_never_reads_the_imported_book(env, paired):
    env.deliver([line(NOW - 30, "a", fresh=4, write=5, read=6, out=7)])
    feed = env.feed()
    paired["reply"] = up(wire())
    assert asyncio.run(peers.pull_once(feed)) is True and feed.peer_book.items[STUDIO_KEY].answer is not None
    served = asyncio.run(feed.local_answer())
    assert sum(b[3] for b in served["windows"]["1h"]) == 6 and "sources" not in served
