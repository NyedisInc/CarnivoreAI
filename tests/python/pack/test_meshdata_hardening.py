from __future__ import annotations

import asyncio
from contextlib import closing
import base64
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import federation_mesh_data_routes as routes
from src.api.peer_auth import Principal
from src.core.computers import direction
from src.core.pack.machines import capabilities as caps
from src.core.pack.machines import exchange
from src.core.pack.machines.roster_v2 import RosterComputerV2, RosterV2
from src.core.pack.machines.settings_sign import Signing
from src.core.pack.meshdata import envelope, gossip, hlc, kinds, panel_kind, status, wire, withhold
from src.core.pack.meshdata.store import RecordStore
from src.core.relay_identity.device_key import DeviceKey, b64url

CERT = base64.b64encode(b"x" * 40).decode()
NOW = 1_800_000_000_000


def uid(i: int) -> str:
    return f"{i:032x}"


def u36(i: int) -> str:
    return f"{i:08x}-0000-0000-0000-{i:012x}"


def pin_key(i: int) -> str:
    return f"l:pin:{u36(0)}/{u36(i)}"


def name_key(i: int) -> str:
    return f"p:{uid(i)}:name"


class World:

    def __init__(self, tmp: Path, *names: str, no_yes: Set[str] = frozenset(), one_way: Set[str] = frozenset(), alpha: Optional[str] = None,
                 home: Optional[str] = None) -> None:
        self.keys = {n: DeviceKey.from_seed(bytes([i + 3]) * 32) for i, n in enumerate(names)}
        self.names, self.no_yes, self.one_way = list(names), set(no_yes), set(one_way)
        self.alpha, self.home = f"iid-{alpha or names[0]}", f"iid-{home or alpha or names[0]}"
        self.now = NOW
        self.signing = {n: Signing(install_id=f"iid-{n}", load_key=lambda n=n: self.keys[n], pinned_key=lambda iid: None) for n in names}
        self.stores = {n: RecordStore(tmp / f"{n}.db", f"iid-{n}", wall=lambda: self.now, signing=self.signing[n]) for n in names}
        self.requests = 0
        self.max_size = 0

    def lst(self) -> RosterV2:
        rows = [RosterComputerV2(install_id=f"iid-{n}", label=n, fed_public_key=b64url(self.keys[n].raw_pub), cert=CERT, mesh=True,
                                 may_receive_logins=n not in self.no_yes, one_way=n in self.one_way) for n in self.names]
        return RosterV2(generation=1, alpha=self.alpha, home=self.home, issued_at=1, computers=rows)

    def entry(self, signer: str, kind: str, key: str, value: Any, ms: int, ctr: int = 0) -> Dict[str, Any]:
        stamp = [ms, ctr, f"iid-{signer}"]
        sig = envelope.sign(envelope.KIND_RECORD, f"{kind}:{key}", stamp, envelope.body_hash(value), self.signing[signer])
        return {"v": value, "s": stamp, "sig": sig.to_dict()}

    def offer(self, dst: str, entries: Dict[str, Any], from_peer: str, lst: Any = None):
        return self.stores[dst].offer_batch(entries, from_peer, lst or self.lst(), self.now)

    def sync(self, src: str, dst: str):
        lst = self.lst()

        async def call(body: Dict[str, Any]) -> Dict[str, Any]:
            self.requests += 1
            self.max_size = max(self.max_size, wire.body_size(body))
            answer, _ = wire.handle_sync(self.stores[dst], json.loads(json.dumps(body)), f"iid-{src}", lst, self.now)
            self.max_size = max(self.max_size, wire.body_size(answer))
            return json.loads(json.dumps(answer))
        return asyncio.run(wire.run_sync(self.stores[src], call, lst, f"iid-{dst}", lambda: self.now))

    def digest(self, name: str, peer: Optional[str] = None) -> str:
        return self.stores[name].view(self.lst(), peer)[1]


@pytest.fixture()
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(caps, "MESH_BUILD_ON", True)
    monkeypatch.setattr(direction, "contained", lambda iid: False)
    monkeypatch.setattr(direction, "one_way_ids", lambda: [])
    return lambda *names, **kw: World(tmp_path, *names, **kw)


def test_a_new_key_is_refused_at_the_kind_cap_and_the_origin_cap_inside_one_batch(world, monkeypatch):
    monkeypatch.setitem(kinds.KINDS, "panel", kinds.KINDS["panel"]._replace(cap=10, origin_cap=6, reserve=0))
    w = world("a", "b", "c", alpha="c")
    batch: Dict[str, Any] = {}
    for i in range(7):
        batch[f"panel:{name_key(i)}"] = w.entry("a", "panel", name_key(i), f"a{i}", NOW)
    for i in range(7, 12):
        batch[f"panel:{name_key(i)}"] = w.entry("b", "panel", name_key(i), f"b{i}", NOW)
    out = w.offer("c", batch, "iid-a")
    assert (out.accepted, out.refused) == (10, 2)
    edit = w.offer("c", {f"panel:{name_key(0)}": w.entry("a", "panel", name_key(0), "edited", NOW + 1000)}, "iid-a")
    assert (edit.accepted, edit.refused) == (1, 0)
    held = w.stores["c"].servable(w.lst())
    assert len([n for n in held if n.startswith("panel:")]) == 10
    assert held[f"panel:{name_key(0)}"]["v"] == "edited" and f"panel:{name_key(6)}" not in held and f"panel:{name_key(11)}" not in held


def test_a_full_size_panel_set_converges_within_the_bucket_and_size_limits(world):
    w = world("a", "b", "c", home="b")
    big = "\U0001F600" * 200
    for origin, base in (("a", 0), ("b", 100_000)):
        entries: Dict[str, Any] = {}
        for i in range(8192):
            if i % 4 == 0:
                key, value = name_key(base + i), big
            else:
                key, value = pin_key(base + i), {"pos": f"a{i % 1000:03d}"}
            entries[f"panel:{key}"] = w.entry(origin, "panel", key, value, NOW + i % 7)
            if len(entries) == 512:
                assert w.offer(origin, entries, f"iid-{origin}").accepted == 512
                entries = {}
        assert w.offer(origin, entries, f"iid-{origin}").accepted == len(entries)
    assert len(w.stores["a"].servable(w.lst())) == 8192
    rounds = 0
    while not (w.digest("a") == w.digest("b") == w.digest("c")):
        rounds += 1
        assert rounds <= 40
        for src, dst in (("a", "c"), ("b", "c"), ("c", "a"), ("c", "b")):
            before = w.requests
            w.sync(src, dst)
            assert w.requests - before <= 2 * wire.MAX_BUCKETS
    assert len(w.stores["c"].servable(w.lst())) == 16384
    assert w.max_size <= wire.HARD_LIMIT_BYTES
    assert all(w.sync(s, d)[0] == "no_change" for s, d in (("a", "c"), ("c", "b")))


def test_a_local_edit_right_after_a_far_ahead_remote_stamp_wins_and_the_clock_stops_there(world):
    w = world("a", "b", "c")
    key = name_key(1)
    far = NOW + 240_000
    assert w.offer("b", {f"panel:{key}": w.entry("a", "panel", key, "remote", far)}, "iid-a").accepted == 1
    assert w.stores["b"].clock().last.ms == NOW + hlc.FOLD_LEAD_MS
    assert w.stores["b"].put_own("panel", key, "local", w.signing["b"])
    mine = w.stores["b"].servable(w.lst())[f"panel:{key}"]
    assert tuple(mine["s"][:2]) == (far, 1) and mine["s"][2] == "iid-b"
    for src, dst in (("b", "a"), ("b", "c"), ("a", "c")):
        w.sync(src, dst)
    assert all(w.stores[n].servable(w.lst())[f"panel:{key}"]["v"] == "local" for n in "abc")
    assert w.stores["b"].put_own("panel", key, "again", w.signing["b"])
    assert w.stores["b"].clock().last.ms == far


def test_an_origin_can_withhold_from_a_computer_and_the_digests_stay_symmetric(world):
    w = world("a", "b", "x")
    key = name_key(2)
    w.stores["b"].put_own("status", "iid-b", status.build("b", "1", [], 1), w.signing["b"])
    w.stores["b"].put_own("panel", key, "secret", w.signing["b"])
    w.stores["b"].put_own("withhold", "iid-b", withhold.build(["iid-x", "iid-x"]), w.signing["b"])
    w.stores["a"].put_own("status", "iid-a", status.build("a", "1", [], 1), w.signing["a"])
    w.stores["a"].put_own("panel", name_key(3), "open", w.signing["a"])
    w.sync("b", "a")
    held = w.stores["a"].servable(w.lst())
    assert {"status:iid-b", f"panel:{key}", "withhold:iid-b"} <= set(held)
    assert set(w.stores["a"].servable(w.lst(), "iid-x")) == {"status:iid-a", f"panel:{name_key(3)}", "withhold:iid-b"}
    assert w.sync("x", "a")[0] == "ok"
    got = w.stores["x"].servable(w.lst())
    assert f"panel:{key}" not in got and "status:iid-b" not in got and f"panel:{name_key(3)}" in got and "withhold:iid-b" in got
    assert w.sync("x", "a")[0] == "no_change" and w.digest("x", "iid-a") == w.digest("a", "iid-x")
    assert withhold.valid({"ids": ["a", "b"]}) and not withhold.valid({"ids": ["b", "a"]}) and not withhold.valid({"ids": ["a"], "x": 1})


def test_the_account_copy_yes_gates_panel_records_and_never_status(world):
    w = world("a", "b", "c", "d", one_way={"b"}, no_yes={"d"})
    key = name_key(4)
    offered = {f"panel:{key}": w.entry("b", "panel", key, "x", NOW), "status:iid-b": w.entry("b", "status", "iid-b", status.build("b", "1", [], 1), NOW)}
    out = w.offer("c", offered, "iid-b")
    assert (out.accepted, out.refused) == (1, 1) and set(w.stores["c"].servable(w.lst())) == {"status:iid-b"}
    assert w.offer("c", {f"panel:{key}": w.entry("d", "panel", key, "ok", NOW)}, "iid-d").accepted == 1
    w.stores["a"].put_own("panel", name_key(5), "y", w.signing["a"])
    w.stores["a"].put_own("status", "iid-a", status.build("a", "1", [], 1), w.signing["a"])
    assert set(w.stores["a"].servable(w.lst(), "iid-b")) == {"status:iid-a"}
    assert set(w.stores["a"].servable(w.lst(), "iid-c")) == {"status:iid-a", f"panel:{name_key(5)}"}
    assert set(w.stores["a"].servable(w.lst(), "iid-d")) == {"status:iid-a", f"panel:{name_key(5)}"}
    assert panel_kind.approved(w.lst(), "iid-a") and panel_kind.approved(w.lst(), "iid-d")
    assert not panel_kind.approved(w.lst(), "iid-b") and not panel_kind.approved(w.lst(), None)


def test_a_tombstone_survives_a_lost_file_and_an_old_copy_stays_out_after_gc(world):
    w = world("a", "b", "c")
    item, group = pin_key(9), f"g:{u36(5)}:gone"
    live = w.entry("a", "panel", item, {"pos": "a1"}, NOW)
    tomb = w.entry("a", "panel", item, {"pos": None}, NOW + 1000)
    for n, order in enumerate(((live, tomb), (tomb, live))):
        fresh = RecordStore(Path(w.stores["c"].path).with_name(f"fresh{n}.db"), "iid-c", wall=lambda: w.now, signing=w.signing["c"])
        for entry in order:
            fresh.offer_batch({f"panel:{item}": entry}, "iid-a", w.lst(), w.now)
        assert fresh.servable(w.lst())[f"panel:{item}"]["v"] == {"pos": None}
    store = w.stores["c"]
    store.offer_batch({f"panel:{item}": tomb, f"panel:{group}": w.entry("a", "panel", group, True, NOW)}, "iid-a", w.lst(), w.now)
    assert store.gc(w.now + 1000) == 0
    later = w.now + panel_kind.TOMB_TTL_MS + 5000
    assert store.gc(later) == 1
    held = store.servable(w.lst())
    assert f"panel:{item}" not in held and held[f"panel:{group}"]["v"] is True
    assert store.offer_batch({f"panel:{item}": live}, "iid-a", w.lst(), later).stale == 1
    assert store.servable(w.lst()).get(f"panel:{item}", {"v": {"pos": None}})["v"] == {"pos": None}


def test_a_single_origin_full_seed_converges_and_the_reserve_belongs_to_the_alpha(world, monkeypatch):
    monkeypatch.setitem(kinds.KINDS, "panel", kinds.KINDS["panel"]._replace(cap=40, origin_cap=12, reserve=8))
    w = world("a", "b", "c", "d")
    lst = w.lst()
    seed = [(name_key(i), f"n{i}", hlc.Stamp(NOW - 100_000 + i, 0, "iid-a")) for i in range(30)]
    assert w.stores["a"].put_many("panel", seed, w.signing["a"], lst) == (30, 0)
    for n in "bc":
        while w.sync(n, "a")[0] != "no_change":
            pass
    assert w.digest("a") == w.digest("b") == w.digest("c") and len(w.stores["c"].kind_rows(lst, "panel")) == 30
    mine = [(name_key(100 + i), f"b{i}", None) for i in range(15)]
    assert w.stores["d"].put_many("panel", mine, w.signing["d"], lst) == (12, 3)
    assert w.offer("a", w.stores["d"].servable(lst), "iid-d").accepted == 2
    while w.sync("c", "a")[0] != "no_change":
        pass
    assert w.stores["c"].put_many("panel", [(name_key(201), "x", None)], w.signing["c"], lst) == (0, 1)
    assert w.stores["a"].put_many("panel", [(name_key(300 + i), "y", None) for i in range(9)], w.signing["a"], lst) == (8, 1)
    assert w.stores["a"].put_many("panel", [(name_key(100), "z", None)], w.signing["a"], lst)[0] == 1


def test_a_computer_that_lost_the_yes_drops_the_rows_and_the_digests_match_again(world):
    w = world("a", "b", "c")
    w.stores["a"].put_own("status", "iid-a", status.build("a", "1", [], 1), w.signing["a"])
    w.stores["c"].put_own("status", "iid-c", status.build("c", "1", [], 1), w.signing["c"])
    w.stores["a"].put_own("panel", name_key(1), "x", w.signing["a"])
    w.sync("c", "a")
    assert f"panel:{name_key(1)}" in w.stores["c"].servable(w.lst())
    w.one_way.add("c")
    lst = w.lst()
    assert w.stores["c"].prune(lst) == 1
    held = w.stores["c"].servable(lst)
    assert f"panel:{name_key(1)}" not in held and "status:iid-a" in held and "status:iid-c" in held
    w.sync("c", "a")
    assert w.sync("c", "a")[0] == "no_change"


def test_an_unknown_local_gate_still_runs_the_withheld_check_in_prune(world, monkeypatch):
    w = world("a", "b", "c")
    row = f"panel:{name_key(2)}"
    w.stores["b"].put_own("panel", name_key(2), "x", w.signing["b"])
    w.stores["b"].put_own("withhold", "iid-b", withhold.build([]), w.signing["b"])
    w.sync("b", "a")
    w.sync("c", "a")
    assert row in w.stores["c"].servable(w.lst())
    w.stores["b"].put_own("withhold", "iid-b", withhold.build(["iid-c"]), w.signing["b"])
    w.sync("b", "a")
    w.sync("c", "a")
    monkeypatch.setitem(kinds.KINDS, "panel", kinds.KINDS["panel"]._replace(local_ok=lambda own, peer: False, forget_ok=lambda own: False))
    assert w.stores["c"].prune(w.lst()) >= 1
    with closing(w.stores["c"]._connect()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM records WHERE kind = 'panel' AND origin = 'iid-b'").fetchone()[0] == 0


def test_rows_of_an_origin_that_withheld_us_are_dropped_and_refused_and_the_digests_match(world):
    w = world("a", "b", "c")
    row = f"panel:{name_key(2)}"
    w.stores["b"].put_own("panel", name_key(2), "x", w.signing["b"])
    w.stores["b"].put_own("withhold", "iid-b", withhold.build([]), w.signing["b"])
    w.sync("b", "a")
    w.sync("c", "a")
    assert row in w.stores["c"].servable(w.lst())
    w.stores["b"].put_own("withhold", "iid-b", withhold.build(["iid-c"]), w.signing["b"])
    w.sync("b", "a")
    w.sync("c", "a")
    w.sync("a", "c")
    held = w.stores["c"].servable(w.lst())
    assert row not in held and "withhold:iid-b" in held
    assert w.sync("a", "c")[0] == "no_change"
    assert w.offer("c", {row: w.entry("b", "panel", name_key(2), "y", NOW + 5)}, "iid-a").refused == 1


def test_a_row_replaced_after_the_light_read_is_left_out_of_the_entries(world):
    w = world("a", "b")
    store = w.stores["a"]
    for i in (1, 2):
        store.put_own("panel", name_key(i), "x", w.signing["a"])
    rows = store._rows(w.lst(), light=True)
    store.put_own("panel", name_key(1), "edited", w.signing["a"])
    entries = store._entries_for(rows)
    assert sorted(e is None for e in entries) == [False, True]
    assert [r[1] for r, e in zip(rows, entries) if e is not None] == [name_key(2)]


def test_an_expired_tombstone_is_refused_and_two_computers_that_both_collected_it_stay_equal(world):
    w = world("a", "b")
    item = pin_key(7)
    tomb = w.entry("a", "panel", item, {"pos": None}, NOW)
    for n in "ab":
        assert w.offer(n, {f"panel:{item}": tomb}, "iid-a").accepted == 1
    w.now = NOW + panel_kind.TOMB_TTL_MS + 10
    assert [w.stores[n].gc(w.now) for n in "ab"] == [1, 1]
    assert w.sync("a", "b")[0] == "no_change" and w.digest("a") == w.digest("b")
    for n in "ab":
        assert w.offer(n, {f"panel:{item}": tomb}, "iid-a").refused == 1
        assert w.stores[n].kind_rows(w.lst(), "panel") == {}


def test_an_old_live_copy_below_a_dropped_delete_is_answered_with_a_new_delete(world):
    w = world("a", "b")
    item, other = pin_key(8), pin_key(9)
    w.stores["a"].put_own("panel", item, {"pos": "a1"}, w.signing["a"])
    w.stores["a"].put_own("panel", other, {"pos": "a2"}, w.signing["a"])
    w.sync("b", "a")
    assert w.stores["a"].put_own("panel", item, {"pos": None}, w.signing["a"])
    dropped = hlc.Stamp(*w.stores["a"].servable(w.lst())[f"panel:{item}"]["s"])
    w.now += 31 * 24 * 3600 * 1000
    assert w.stores["a"].gc(w.now) == 1
    w.stores["a"].drop("panel", other)
    assert w.stores["a"].offer_batch({f"panel:{other}": w.entry("a", "panel", other, {"pos": "a0"}, NOW - 10)}, "iid-b", w.lst(), w.now).stale == 1
    assert f"panel:{other}" not in w.stores["a"].servable(w.lst())
    while w.sync("b", "a")[0] != "no_change":
        pass
    for n in "ab":
        got = w.stores[n].servable(w.lst())[f"panel:{item}"]
        assert got["v"] == {"pos": None} and hlc.Stamp(*got["s"]) > dropped
    assert w.sync("b", "a")[0] == "no_change"


def test_put_own_with_a_list_writes_no_panel_record_for_a_computer_without_the_yes(world):
    w = world("a", "b", "c", one_way={"b"}, no_yes={"c"})
    lst = w.lst()
    assert not w.stores["b"].put_own("panel", name_key(3), "x", w.signing["b"], lst=lst)
    assert w.stores["b"].put_many("panel", [(name_key(3), "x", None)], w.signing["b"], lst) == (0, 0)
    assert w.stores["b"].kind_rows(lst, "panel") == {}
    assert w.stores["b"].put_own("status", "iid-b", status.build("b", "1", [], 1), w.signing["b"], lst=lst)
    assert w.stores["c"].put_own("panel", name_key(4), "y", w.signing["c"], lst=lst)
    assert w.stores["a"].put_own("panel", name_key(3), "x", w.signing["a"], lst=lst)
    assert w.stores["a"].store_id() and w.stores["a"].store_id() != w.stores["b"].store_id()


def _route_client(monkeypatch, store: Any, lst: Any, caller: str, service_on: bool = True) -> TestClient:
    monkeypatch.setattr(caps, "MESH_BUILD_ON", True)
    monkeypatch.setattr(exchange, "RUNTIME", SimpleNamespace(held_list=lambda: lst))
    monkeypatch.setattr(gossip, "ACTIVE", SimpleNamespace(store=store) if service_on else None)
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    app.dependency_overrides[routes._require_machine] = lambda: Principal("peer", SimpleNamespace(peer_install_id=caller))
    return TestClient(app)


def test_the_sync_route_refuses_and_answers_as_designed_with_the_switch_on(world, monkeypatch, tmp_path):
    w = world("a", "b", "c", one_way={"c"})
    body = {"v": 1, "digest": "d", "buckets": 1, "bucket": 0, "records": {}}
    url = "/api/v1/federation/pack/mesh/sync"
    store = w.stores["a"]
    w.stores["a"].put_own("status", "iid-a", status.build("a", "1", [], 1), w.signing["a"])
    watcher = sqlite3.connect(store.path)
    marker = watcher.execute("PRAGMA data_version").fetchone()[0]
    listed = _route_client(monkeypatch, store, w.lst(), "iid-c")
    refused = listed.post(url, json=body)
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == direction.REFUSAL_CODE
    monkeypatch.setattr(direction, "contained", lambda iid: iid == "iid-b")
    contained = _route_client(monkeypatch, store, w.lst(), "iid-b")
    assert contained.post(url, json=body).status_code == 403
    monkeypatch.setattr(direction, "contained", lambda iid: False)
    unlisted = _route_client(monkeypatch, store, w.lst(), "iid-stranger")
    answer = unlisted.post(url, json={**body, "records": {"status:iid-stranger": {}}})
    assert (answer.status_code, answer.json()) == (200, {"status": "no_change"})
    assert watcher.execute("PRAGMA data_version").fetchone()[0] == marker
    off = _route_client(monkeypatch, store, w.lst(), "iid-b", service_on=False)
    assert off.post(url, json=body).status_code == 503 and off.post(url, json=body).json()["detail"]["code"] == "meshdata_unavailable"
    on = _route_client(monkeypatch, store, w.lst(), "iid-b")

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(wire, "handle_sync", broken)
    failed = on.post(url, json=body)
    assert failed.status_code == 503 and failed.json()["detail"]["code"] == "meshdata_unavailable"
    watcher.close()


def test_member_replay_of_alpha_copies_never_takes_the_reserve(world, monkeypatch):
    monkeypatch.setitem(kinds.KINDS, "panel", kinds.KINDS["panel"]._replace(cap=40, origin_cap=40, reserve=8))
    w = world("a", "b")
    a = w.stores["a"]
    day = 24 * 3600 * 1000
    old = {}
    for i in range(8):
        k = pin_key(100 + i)
        old[f"panel:{k}"] = w.entry("a", "panel", k, {"pos": "a1"}, NOW + i)
        w.offer("a", {f"panel:{k}": old[f"panel:{k}"]}, "iid-a")
        w.offer("a", {f"panel:{k}": w.entry("a", "panel", k, {"pos": None}, NOW + 100 + i)}, "iid-a")
    w.now = NOW + 31 * day
    assert a.gc(w.now) == 8
    fill = {f"panel:{name_key(i)}": w.entry("b", "panel", name_key(i), "x", w.now + i) for i in range(32)}
    assert w.offer("a", fill, "iid-b").accepted == 32
    w.offer("a", old, "iid-b")
    assert len(a.kind_rows(w.lst(), "panel")) == 32


DAY = 24 * 3600 * 1000


def _floors(w: World, store: str, keys: List[str], base: int = NOW) -> Dict[str, Any]:
    old: Dict[str, Any] = {}
    for i, k in enumerate(keys):
        old[f"panel:{k}"] = w.entry("a", "panel", k, {"pos": "a1"}, base + i)
        w.offer(store, {f"panel:{k}": old[f"panel:{k}"]}, "iid-a")
        w.offer(store, {f"panel:{k}": w.entry("a", "panel", k, {"pos": None}, base + 100 + i)}, "iid-a")
    w.now = base + 31 * DAY
    assert w.stores[store].gc(w.now) == len(keys)
    return old


def _fill(w: World, store: str, n: int, start: int = 0) -> None:
    batch = {f"panel:{name_key(start + i)}": w.entry("b", "panel", name_key(start + i), "x", w.now + i) for i in range(n)}
    assert w.offer(store, batch, "iid-b").accepted == n


def _rows(w: World, store: str) -> int:
    return len([n for n in w.stores[store].servable(w.lst()) if n.startswith("panel:")])


def _scaled(monkeypatch) -> None:
    monkeypatch.setitem(kinds.KINDS, "panel", kinds.KINDS["panel"]._replace(cap=40, origin_cap=40, reserve=8))


def _settle(w: World, names: List[str]) -> None:
    for _ in range(12):
        for n in names:
            w.stores[n].prune(w.lst())
        for s in names:
            for d in names:
                if s != d:
                    w.sync(s, d)
        if all(w.sync(s, d)[0] == "no_change" for s in names for d in names if s != d):
            return
    raise AssertionError("never reached no_change")


def test_an_overlapping_reassert_on_the_alpha_never_signs_past_the_member_limit(world, monkeypatch):
    _scaled(monkeypatch)
    w = world("a", "b")
    keys = [pin_key(200 + i) for i in range(3)]
    _floors(w, "a", keys)
    _fill(w, "a", 31)
    w.stores["a"]._reassert([("panel", k) for k in keys], w.lst())
    assert _rows(w, "a") == 32
    assert sum(1 for n, e in w.stores["a"].servable(w.lst()).items() if e["v"] == {"pos": None}) == 1


def test_member_room_drops_only_the_reserve_exemption_not_the_alpha_origin_exemption():
    rule = kinds.KINDS["panel"]._replace(cap=40, reserve=8, origin_cap=10, privileged=lambda lst, origin: origin == "iid-a")
    ok = lambda origin, kind_n, origin_n, member: RecordStore._room_ok(rule, None, origin, kind_n, origin_n, member=member)
    assert ok("iid-a", 12, 12, True) and ok("iid-a", 12, 12, False)
    assert not ok("iid-a", 32, 12, True) and ok("iid-a", 32, 12, False)
    assert not ok("iid-b", 12, 10, True)


def test_in_batch_reasserts_count_toward_the_member_limit(world, monkeypatch):
    _scaled(monkeypatch)
    w = world("a", "b")
    old = _floors(w, "a", [pin_key(300 + i) for i in range(8)])
    _fill(w, "a", 28)
    calls: List[str] = []
    real = w.stores["a"].put_own
    monkeypatch.setattr(w.stores["a"], "put_own", lambda *a, **k: calls.append(a[1]) or real(*a, **k))
    w.offer("a", old, "iid-b")
    assert len(calls) == 4 and _rows(w, "a") == 32


def test_an_origin_that_loses_approval_after_its_rows_spread_is_dropped_everywhere_and_the_copies_converge(world):
    w = world("a", "b", "c", "d", "e")
    key = name_key(1)
    first = w.entry("a", "panel", key, "a-value", NOW)
    assert w.offer("a", {f"panel:{key}": first}, "iid-a").accepted == 1
    w.sync("d", "a")
    w.now = NOW + 1000
    w.stores["b"].put_own("panel", key, "b-value", w.signing["b"])
    w.sync("b", "a")
    w.sync("c", "a")
    assert w.stores["c"].kind_rows(w.lst(), "panel")[key][0] == "b-value"
    w.one_way.add("b")
    names = ["a", "c", "d", "e"]
    _settle(w, names)
    for n in names:
        rows = w.stores[n].kind_rows(w.lst(), "panel")
        assert {k: v[0] for k, v in rows.items()} == {key: "a-value"} and rows[key][1] == hlc.Stamp(NOW, 0, "iid-a")
    assert len({w.stores[n].kind_digest(w.lst(), "panel") for n in names}) == 1
    assert w.offer("c", {f"panel:{key}": w.entry("b", "panel", key, "again", NOW + 5000)}, "iid-a").refused == 1


def test_an_origin_contained_only_here_is_stored_and_forwarded_but_never_applied(world, monkeypatch):
    w = world("a", "b", "c", "e")
    key = name_key(2)
    w.stores["b"].put_own("panel", key, "b-value", w.signing["b"])
    w.sync("b", "a")
    w.sync("c", "a")
    empty = w.stores["e"].kind_digest(w.lst(), "panel")
    monkeypatch.setattr(direction, "contained", lambda iid: iid == "iid-b")
    monkeypatch.setattr(direction, "one_way_ids", lambda: ["iid-b"])
    _settle(w, ["a", "c"])
    assert f"panel:{key}" in w.stores["c"].servable(w.lst()) and w.sync("c", "a")[0] == "no_change"
    assert w.stores["c"].kind_rows(w.lst(), "panel") == {} and w.stores["c"].kind_digest(w.lst(), "panel") == empty
    monkeypatch.setattr(direction, "contained", lambda iid: False)
    monkeypatch.setattr(direction, "one_way_ids", lambda: [])
    assert w.stores["c"].kind_digest(w.lst(), "panel") != empty and key in w.stores["c"].kind_rows(w.lst(), "panel")


def test_a_reasserted_delete_never_beats_an_honest_readd_made_after_it(world):
    w = world("a", "b", "c")
    k = pin_key(400)
    old = _floors(w, "a", [k])
    assert w.offer("c", old, "iid-b").accepted == 1
    stamp = w.now
    readd = {f"panel:{k}": w.entry("b", "panel", k, {"pos": "b9"}, stamp)}
    assert w.offer("a", readd, "iid-b").accepted == 1
    got = w.offer("a", old, "iid-b")
    assert (got.stale, got.accepted) == (1, 0) and w.stores["a"].servable(w.lst())[f"panel:{k}"]["v"] == {"pos": "b9"}
    assert w.sync("c", "a")[0] in ("ok", "no_change") and w.stores["c"].servable(w.lst())[f"panel:{k}"]["v"] == {"pos": "b9"}
    other = pin_key(401)
    old2 = _floors(w, "a", [other], base=w.now)
    w.offer("c", old2, "iid-b")
    w.sync("c", "a")
    tomb = hlc.Stamp(*w.stores["a"].servable(w.lst())[f"panel:{other}"]["s"])
    assert w.offer("a", {f"panel:{other}": w.entry("b", "panel", other, {"pos": "b1"}, tomb.ms + 1)}, "iid-b").accepted == 1
    _settle(w, ["a", "b", "c"])
    assert all(w.stores[n].servable(w.lst())[f"panel:{other}"]["v"] == {"pos": "b1"} for n in "abc")


def test_at_the_member_limit_an_old_copy_waits_and_is_answered_once_room_frees(world, monkeypatch):
    _scaled(monkeypatch)
    w = world("a", "b")
    k = pin_key(500)
    old = {f"panel:{k}": w.entry("a", "panel", k, {"pos": "a1"}, NOW)}
    w.offer("b", old, "iid-a")
    w.offer("a", old, "iid-a")
    w.offer("a", {f"panel:{k}": w.entry("a", "panel", k, {"pos": None}, NOW + 100)}, "iid-a")
    w.now = NOW + 29 * DAY
    pins = {f"panel:{pin_key(600 + i)}": w.entry("b", "panel", pin_key(600 + i), {"pos": None}, w.now + i) for i in range(3)}
    assert w.offer("a", pins, "iid-b").accepted == 3
    _fill(w, "a", 28)
    w.now = NOW + 30 * DAY + 1000
    assert w.stores["a"].gc(w.now) == 1
    _fill(w, "a", 1, start=500)
    assert _rows(w, "a") == 32
    answer = w.stores["a"].offer_batch(old, "iid-b", w.lst(), w.now)
    assert answer.stale == 1 and _rows(w, "a") == 32 and f"panel:{k}" not in w.stores["a"].servable(w.lst())
    w.now = NOW + 60 * DAY
    assert w.stores["a"].gc(w.now) == 3 and _rows(w, "a") == 29
    w.sync("b", "a")
    assert w.stores["a"].servable(w.lst())[f"panel:{k}"]["v"] == {"pos": None}
    _settle(w, ["a", "b"])
    assert w.stores["b"].servable(w.lst())[f"panel:{k}"]["v"] == {"pos": None}


def test_prune_is_memoized_on_the_list_and_the_withhold_rows(world, monkeypatch):
    w = world("a", "b", "c")
    row = f"panel:{name_key(3)}"
    w.stores["b"].put_own("panel", name_key(3), "x", w.signing["b"])
    w.stores["b"].put_own("withhold", "iid-b", withhold.build([]), w.signing["b"])
    w.sync("b", "a")
    w.sync("c", "a")
    seen: List[str] = []
    real = RecordStore._withholders
    monkeypatch.setattr(RecordStore, "_withholders", staticmethod(lambda *a: seen.append("x") or real(*a)))
    c, lst = w.stores["c"], w.lst()
    assert c.prune(lst) == 0 and len(seen) == 1
    assert w.offer("c", {"status:iid-a": w.entry("a", "status", "iid-a", status.build("a", "1", [], 1), NOW)}, "iid-a").accepted == 1
    before = len(seen)
    assert c.prune(lst) == 0 and len(seen) == before
    w.stores["b"].put_own("withhold", "iid-b", withhold.build(["iid-c"]), w.signing["b"])
    w.sync("b", "a")
    w.sync("c", "a")
    assert row in c.servable(lst)
    assert c.prune(lst) == 1 and len(seen) > before and row not in c.servable(lst)


def test_an_offer_under_another_list_clears_the_prune_memo_so_the_next_prune_drops_the_rows(world):
    w = world("a", "b", "c")
    l0 = w.lst()
    w.one_way.add("b")
    l1 = w.lst()
    w.one_way.discard("b")
    c = w.stores["c"]
    assert c.prune(l1) == 0
    key = name_key(7)
    assert w.offer("c", {f"panel:{key}": w.entry("b", "panel", key, "x", NOW)}, "iid-b", l0).accepted == 1
    assert c.prune(l1) == 1 and f"panel:{key}" not in c.servable(l1)


def test_a_batch_admitted_while_a_prune_is_reading_leaves_the_memo_unset_so_the_next_prune_examines_it(world, tmp_path):
    w = world("a", "b", "c")
    l1 = w.lst()
    w.one_way.add("b")
    l2 = w.lst()
    w.one_way.discard("b")
    key = name_key(9)
    offered = {f"panel:{key}": w.entry("b", "panel", key, "x", NOW)}
    fired: List[bool] = []

    class Conn:

        def __init__(self, real: sqlite3.Connection, store: "Racing") -> None:
            self.real, self.store = real, store

        def execute(self, sql: str, *args: Any) -> Any:
            if sql == "SELECT kind, key, origin FROM records" and not fired:
                fired.append(True)
                rows = self.real.execute(sql, *args).fetchall()
                assert self.store.offer_batch(offered, "iid-b", l1, NOW).accepted == 1
                return SimpleNamespace(fetchall=lambda: rows)
            return self.real.execute(sql, *args)

        def close(self) -> None:
            self.real.close()

        def __enter__(self) -> Any:
            self.real.__enter__()
            return self

        def __exit__(self, *exc: Any) -> Any:
            return self.real.__exit__(*exc)

        def __getattr__(self, name: str) -> Any:
            return getattr(self.real, name)

    class Racing(RecordStore):
        def _connect(self) -> Any:
            return Conn(super()._connect(), self)

    c = Racing(tmp_path / "racing.db", "iid-c", wall=lambda: NOW, signing=w.signing["c"])
    assert c.prune(l2) == 0 and fired
    assert c.prune(l2) == 1 and f"panel:{key}" not in c.servable(l2)


def test_put_own_with_a_list_refuses_a_members_new_key_at_the_member_limit(world, monkeypatch):
    _scaled(monkeypatch)
    w = world("a", "b")
    lst = w.lst()
    assert all(w.stores["b"].put_own("panel", name_key(i), "x", w.signing["b"], lst=lst) for i in range(32))
    assert not w.stores["b"].put_own("panel", name_key(99), "x", w.signing["b"], lst=lst)
    assert w.stores["b"].put_own("panel", name_key(0), "edited", w.signing["b"], lst=lst)
    w.offer("a", w.stores["b"].servable(lst), "iid-b")
    assert all(w.stores["a"].put_own("panel", name_key(100 + i), "x", w.signing["a"], lst=lst) for i in range(8))
    assert not w.stores["a"].put_own("panel", name_key(200), "x", w.signing["a"], lst=lst)


def test_a_4b_era_file_with_records_and_a_clock_gains_the_tomb_column_and_a_store_id_and_keeps_its_records(world, tmp_path):
    w = world("a", "b")
    path = tmp_path / "old4b.db"
    key = name_key(5)
    entry = w.entry("b", "panel", key, "x", NOW)
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE records (kind TEXT NOT NULL, key TEXT NOT NULL, value_json TEXT NOT NULL, ms INTEGER NOT NULL, ctr INTEGER NOT NULL,
        origin TEXT NOT NULL, h TEXT NOT NULL, sig_json TEXT NOT NULL, kid TEXT NOT NULL, direct INTEGER NOT NULL DEFAULT 0,
        received_ms INTEGER NOT NULL, PRIMARY KEY (kind, key))""")
    conn.execute("CREATE TABLE floors (kind TEXT NOT NULL, key TEXT NOT NULL, ms INTEGER NOT NULL, ctr INTEGER NOT NULL, iid TEXT NOT NULL, PRIMARY KEY (kind, key))")
    conn.execute("CREATE TABLE meta (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
    lst = w.lst()
    conn.execute("INSERT INTO records VALUES ('panel', ?, ?, ?, 0, 'iid-b', ?, ?, ?, 1, ?)",
                 (key, json.dumps("x"), NOW, envelope.body_hash("x"), json.dumps(entry["sig"]), envelope.kid(lst.entry("iid-b").fed_public_key), NOW))
    conn.execute("INSERT INTO meta VALUES ('clock', ?)", (json.dumps([NOW, 0, "iid-a"]),))
    conn.commit()
    conn.close()
    store = RecordStore(path, "iid-a", wall=lambda: w.now, signing=w.signing["a"])
    with sqlite3.connect(path) as check:
        assert "tomb" in [r[1] for r in check.execute("PRAGMA table_info(floors)")]
        assert check.execute("SELECT COUNT(*) FROM meta WHERE name = 'store_id'").fetchone()[0] == 1
    assert len(store.store_id()) == 32
    assert store.kind_rows(lst, "panel")[key][0] == "x"


def test_a_4b_era_floors_table_gains_the_tomb_column_and_its_floors_never_reassert(world, tmp_path):
    path = tmp_path / "old.db"
    k = pin_key(700)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE floors (kind TEXT NOT NULL, key TEXT NOT NULL, ms INTEGER NOT NULL, ctr INTEGER NOT NULL, iid TEXT NOT NULL, PRIMARY KEY (kind, key))")
    conn.execute("INSERT INTO floors VALUES ('panel', ?, ?, 0, 'iid-a')", (k, NOW + 500))
    conn.commit()
    conn.close()
    w = world("a", "b")
    store = RecordStore(path, "iid-a", wall=lambda: w.now, signing=w.signing["a"])
    with sqlite3.connect(path) as check:
        assert "tomb" in [r[1] for r in check.execute("PRAGMA table_info(floors)")]
        assert check.execute("SELECT tomb FROM floors").fetchone()[0] == 0
    out = store.offer_batch({f"panel:{k}": w.entry("a", "panel", k, {"pos": "a1"}, NOW)}, "iid-b", w.lst(), w.now)
    assert (out.stale, out.accepted) == (1, 0) and store.kind_rows(w.lst(), "panel") == {}


def test_the_real_sizes_hold_on_one_run(world):
    w = world("a", "b", "c")
    lst = w.lst()
    b_cap = panel_kind.ORIGIN_CAP
    c_cap = panel_kind.CAP - panel_kind.RESERVE - b_cap
    a_cap = panel_kind.RESERVE
    assert w.stores["b"].put_many("panel", [(name_key(i), "x", None) for i in range(b_cap + 1)], w.signing["b"], lst) == (b_cap, 1)
    assert w.stores["c"].put_many("panel", [(name_key(100_000 + i), "x", None) for i in range(c_cap + 1)], w.signing["c"], lst) == (c_cap + 1, 0)
    hub = w.stores["a"]
    assert hub.offer_batch(w.stores["b"].servable(lst), "iid-b", lst, w.now).accepted == b_cap
    out = hub.offer_batch(w.stores["c"].servable(lst), "iid-c", lst, w.now)
    assert (out.accepted, out.refused) == (c_cap, 1)
    assert hub.put_many("panel", [(name_key(200_000 + i), "x", None) for i in range(a_cap + 1)], w.signing["a"], lst) == (a_cap, 1)
    assert len(hub.kind_rows(lst, "panel")) == panel_kind.CAP
