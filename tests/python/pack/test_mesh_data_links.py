from __future__ import annotations

import asyncio
import base64
import copy
import json
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set, Tuple

import pytest

from src.api import federation_mesh_data_routes as route
from src.core.computers import direction
from src.core.federation import mesh_powers
from src.core.notifications.sync.secrets_sync import RateLimiter
from src.core.pack.jobs import member_view
from src.core.pack.machines import capabilities as caps
from src.core.pack.machines.roster_v2 import RosterComputerV2, RosterV2
from src.core.pack.machines.settings_sign import Signing
from src.core.pack.meshdata import envelope, gossip, hlc, kinds, panel_kind, wire
from src.core.pack.meshdata.store import RecordStore
from src.core.relay_identity.device_key import DeviceKey, b64url

CERT = base64.b64encode(b"x" * 40).decode()


def uid(i: int) -> str:
    return f"{i:032x}"


def u36(i: int) -> str:
    return f"{i:08x}-0000-0000-0000-{i:012x}"


def name_key(i: int) -> str:
    return f"p:{uid(i)}:name"


def pin_key(i: int) -> str:
    return f"l:pin:{u36(0)}/{u36(i)}"


class Reply:

    def __init__(self, body: Dict[str, Any]) -> None:
        self.status_code, self._body = 200, body

    def json(self) -> Dict[str, Any]:
        return self._body


class Client:

    def __init__(self, world: "World", src: str, dst: str) -> None:
        self.world, self.src, self.dst = world, src, dst
        self.calls = 0

    async def request(self, method: str, path: str, json: Optional[dict] = None, **_kw: Any) -> Reply:
        assert (method, path) == ("POST", gossip.SYNC_PATH), (method, path)
        self.calls += 1
        answer, _ = wire.handle_sync(self.world.stores[self.dst], copy.deepcopy(json), f"iid-{self.src}", self.world.lst(), hlc.wall_ms())
        return Reply(answer)


class Registry:

    def __init__(self, links: List[Tuple[str, Any]], no_cap: Set[str] = frozenset()) -> None:
        self._links, self._no_cap = links, set(no_cap)

    def connected(self) -> List[Tuple[str, Any]]:
        return list(self._links)

    def capabilities(self, iid: str) -> List[str]:
        return [] if iid in self._no_cap else [caps.CAP_MESH]

    def connect(self, *_a: Any, **_k: Any) -> None:
        raise AssertionError("connect")

    ensure = client = _touch = connect


class MeshApi:

    def __init__(self, lst: Any, untrusted: Set[str] = frozenset(), on_demand: Set[str] = frozenset()) -> None:
        self._lst, self._untrusted, self._on_demand = lst, set(untrusted), set(on_demand)

    def trusted(self, iid: str) -> Any:
        return None if iid in self._untrusted else self._lst

    def on_demand(self, iid: str) -> bool:
        return iid in self._on_demand


class World:

    def __init__(self, tmp: Path, names: List[str], no_yes: Set[str] = frozenset(), one_way: Set[str] = frozenset()) -> None:
        self.names, self.no_yes, self.one_way = list(names), set(no_yes), set(one_way)
        self.keys = {n: DeviceKey.from_seed(bytes([i + 3]) * 32) for i, n in enumerate(["z"] + self.names)}
        self.signing = {n: Signing(install_id=f"iid-{n}", load_key=lambda n=n: self.keys[n], pinned_key=lambda iid: None) for n in self.keys}
        self.stores = {n: RecordStore(tmp / f"{n}.db", f"iid-{n}", signing=self.signing[n]) for n in self.names}
        self.removed: Set[str] = set()
        self.clients: Dict[Tuple[str, str], Client] = {}
        self.services: Dict[str, gossip.Gossip] = {}

    def lst(self) -> RosterV2:
        rows = [RosterComputerV2(install_id=f"iid-{n}", label=n, fed_public_key=b64url(self.keys[n].raw_pub), cert=CERT, mesh=True,
                                 may_receive_logins=n not in self.no_yes, one_way=n in self.one_way) for n in ["z"] + self.names if n not in self.removed]
        return RosterV2(generation=1, alpha="iid-z", home="iid-z", issued_at=1, computers=rows)

    def link(self, pairs: List[Tuple[str, str]]) -> None:
        for a, b in pairs:
            self.clients[(a, b)], self.clients[(b, a)] = Client(self, a, b), Client(self, b, a)
        for n in self.names:
            reg = Registry([(f"iid-{d}", c) for (s, d), c in self.clients.items() if s == n])
            self.services[n] = gossip.Gossip(
                self.stores[n], links_getter=lambda: None, signing=self.signing[n], held_list=self.lst, label=lambda n=n: n, app_version="1.0", own_iid=f"iid-{n}",
                members=lambda lst, n=n, reg=reg: gossip.member_links(lst, f"iid-{n}", reg, MeshApi(lst)))

    def run(self, name: str) -> None:
        asyncio.run(self.services[name].pass_once())

    def entry(self, signer: str, kind: str, key: str, value: Any, ms: int, ctr: int = 0) -> Dict[str, Any]:
        stamp = [ms, ctr, f"iid-{signer}"]
        sig = envelope.sign(envelope.KIND_RECORD, f"{kind}:{key}", stamp, envelope.body_hash(value), self.signing[signer])
        return {"v": value, "s": stamp, "sig": sig.to_dict()}

    def offer(self, dst: str, entries: Dict[str, Any], via: str, lst: Any = None) -> Any:
        return self.stores[dst].offer_batch(entries, f"iid-{via}", lst or self.lst(), hlc.wall_ms())

    def panel(self, name: str, key: str, value: Any) -> bool:
        return self.stores[name].put_own("panel", key, value, self.signing[name], lst=self.lst())


@pytest.fixture()
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(caps, "MESH_BUILD_ON", True)
    monkeypatch.setattr(direction, "contained", lambda iid: False)
    monkeypatch.setattr(direction, "one_way_ids", lambda: [])
    monkeypatch.setattr(gossip, "STEPS", [])
    return lambda names, **kw: World(tmp_path, names, **kw)


def _lst(own: str, rows: Dict[str, dict]) -> RosterV2:
    keys = {n: DeviceKey.from_seed(bytes([i + 40]) * 32) for i, n in enumerate(["z", own, *rows])}
    entries = [RosterComputerV2(install_id=f"iid-{n}", label=n, fed_public_key=b64url(keys[n].raw_pub), cert=CERT, mesh=True, **({} if n in ("z", own) else rows[n]))
               for n in keys]
    return RosterV2(generation=1, alpha="iid-z", home="iid-z", issued_at=1, computers=entries)


def test_member_links_pick_only_a_standing_two_way_pinned_mesh_member_and_never_dial(monkeypatch):
    monkeypatch.setattr(caps, "MESH_BUILD_ON", True)
    monkeypatch.setattr(direction, "contained", lambda iid: iid == "iid-d")
    monkeypatch.setattr(direction, "is_one_way_toward", lambda iid: False)
    rows = {"b": {}, "c": {"one_way": True}, "d": {}, "e": {"link_peers": False}, "g": {}, "h": {}, "i": {}, "j": {}}
    lst = _lst("m", rows)
    ids = ["b", "c", "d", "e", "f", "g", "h", "i", "j"]
    reg = Registry([(f"iid-{n}", object()) for n in ids], no_cap={"iid-h"})
    api = MeshApi(lst, untrusted={"iid-i"}, on_demand={"iid-g"})
    assert [i for i, _ in gossip.member_links(lst, "iid-m", reg, api)] == ["iid-b", "iid-j"]
    star = SimpleNamespace(connected_clients=lambda: [("iid-j", "star-client")], capabilities=lambda iid: [caps.CAP_MESH])
    svc = gossip.Gossip(None, links_getter=lambda: star, signing=None, held_list=lambda: lst, label=lambda: "m", app_version="1", own_iid="iid-m",  # type: ignore[arg-type]
                        members=lambda lst_: gossip.member_links(lst_, "iid-m", reg, api))
    assert [(i, c) for i, c in svc.peers(lst)] == [("iid-j", "star-client"), ("iid-b", reg.connected()[0][1])]
    assert gossip.member_links(_own_one_way(), "iid-m", reg, api) == []
    assert gossip.member_links(lst, "iid-m", None, api) == []
    monkeypatch.setattr(caps, "MESH_BUILD_ON", False)
    assert gossip.member_links(lst, "iid-m", reg, api) == []


def _own_one_way() -> RosterV2:
    base = _lst("m", {"b": {}})
    rows = [c.model_copy(update={"one_way": c.install_id == "iid-m"}) for c in base.computers]
    return base.model_copy(update={"computers": rows})


def test_two_members_with_the_alpha_down_converge_and_hold_each_others_cards(world, monkeypatch):
    w = world(["a", "b", "c"])
    w.link([("a", "b"), ("b", "c")])
    key = name_key(1)
    assert w.panel("a", key, "renamed") and w.stores["a"].put_own("ops", "auto_distribute", True, w.signing["a"], lst=w.lst())
    for n in ("a", "b", "c"):
        w.run(n)
    w.run("b")
    lst = w.lst()
    for name in (f"panel:{key}", "ops:auto_distribute"):
        assert w.stores["c"].servable(lst)[name] == w.stores["a"].servable(lst)[name]
    heard = w.stores["c"].heard(lst, hlc.wall_ms())
    assert heard["iid-b"]["via"] == "direct" and heard["iid-a"]["via"] == "passed" and heard["iid-a"]["label"] == "a"
    assert all(h["age_s"] <= member_view.CARD_MAX_AGE_S for h in heard.values())
    monkeypatch.setattr(gossip, "ACTIVE", w.services["c"])
    assert {"iid-a", "iid-b"} <= set(gossip.heard_now())
    assert ("z", "a") not in w.clients and not any("iid-z" in (c.src, c.dst) for c in w.clients.values())


def test_a_forwarder_cannot_alter_forge_replay_or_resurrect(world):
    w = world(["a", "b", "c"])
    now = hlc.wall_ms()
    key, pin = name_key(2), pin_key(2)
    new = w.entry("a", "panel", key, "new", now - 1000)
    old = w.entry("a", "panel", key, "old", now - 5000)
    altered = copy.deepcopy(new)
    altered["v"] = "evil"
    out = w.offer("c", {f"panel:{key}": altered}, "b")
    assert out.accepted == 0 and out.bad_origins == {"iid-a"}
    forged = w.entry("b", "panel", name_key(3), "forged", now)
    forged["s"][2] = "iid-a"
    assert w.offer("c", {f"panel:{name_key(3)}": forged}, "b").accepted == 0
    assert w.offer("c", {f"panel:{key}": new}, "b").accepted == 1
    assert w.offer("c", {f"panel:{key}": old}, "b").accepted == 0
    assert w.stores["c"].servable(w.lst())[f"panel:{key}"]["v"] == "new"
    live = w.entry("a", "panel", pin, {"pos": "a1"}, now - 4000)
    gone = w.entry("a", "panel", pin, {"pos": None}, now - 3000)
    assert w.offer("c", {f"panel:{pin}": gone}, "b").accepted == 1
    assert w.offer("c", {f"panel:{pin}": live}, "b").accepted == 0
    assert w.stores["c"].servable(w.lst())[f"panel:{pin}"]["v"] == {"pos": None}
    assert name_key(3) not in " ".join(w.stores["c"].servable(w.lst()))


def test_a_removed_computer_is_dropped_everywhere_and_stays_refused(world):
    w = world(["a", "b", "c"])
    w.link([("a", "b"), ("b", "c")])
    w.panel("a", name_key(4), "x")
    for n in ("a", "b", "c", "b"):
        w.run(n)
    before = {n: e for n, e in w.stores["c"].servable(w.lst()).items() if e["s"][2] == "iid-a"}
    assert before
    w.removed.add("a")
    w.run("c")
    lst = w.lst()
    assert not [n for n, e in w.stores["c"].servable(lst).items() if e["s"][2] == "iid-a"]
    assert not [n for n, e in w.stores["b"].servable(lst, "iid-c").items() if e["s"][2] == "iid-a"]
    with closing(w.stores["c"]._connect()) as conn:  # noqa: SLF001
        assert conn.execute("SELECT COUNT(*) FROM floors WHERE iid = ?", ("iid-a",)).fetchone()[0] >= 1
    out = w.offer("c", before, "b", lst)
    assert out.accepted == 0 and out.refused == len(before)


def test_a_member_cannot_fill_the_panel_through_a_third_member(world, monkeypatch):
    monkeypatch.setitem(kinds.KINDS, "panel", kinds.KINDS["panel"]._replace(cap=12, origin_cap=5, reserve=4))
    w = world(["a", "b", "c", "d", "e"])
    now = hlc.wall_ms()
    for origin in ("d", "a", "e"):
        batch = {f"panel:{name_key(100 * ord(origin) + i)}": w.entry(origin, "panel", name_key(100 * ord(origin) + i), "v", now - 1000) for i in range(20)}
        w.offer("c", batch, "b")
    rows = {n: e for n, e in w.stores["c"].servable(w.lst()).items() if n.startswith("panel:")}
    per = {o: sum(1 for e in rows.values() if e["s"][2] == f"iid-{o}") for o in "dae"}
    assert per["d"] == 5 and sum(per.values()) == 8 and max(per.values()) <= 5
    alpha = w.entry("z", "panel", name_key(7), "alpha", now - 1000)
    assert w.offer("c", {f"panel:{name_key(7)}": alpha}, "b").accepted == 1


def test_panel_records_reach_only_computers_approved_for_account_copies(world):
    from src.core.pack.meshdata import status

    w = world(["a", "b", "c", "d"], one_way={"c"}, no_yes={"d"})
    entry = w.entry("a", "panel", name_key(5), "x", hlc.wall_ms() - 1000)
    assert w.offer("b", {f"panel:{name_key(5)}": entry}, "a").accepted == 1
    w.stores["a"].put_own("ops", "auto_distribute", True, w.signing["a"], lst=w.lst())
    w.stores["a"].put_own("status", "iid-a", status.build("a", "1", [], 1), w.signing["a"], lst=w.lst())
    serv = w.stores["a"].servable(w.lst())
    w.offer("b", {"ops:auto_distribute": serv["ops:auto_distribute"], "status:iid-a": serv["status:iid-a"]}, "a")
    to_approved = w.stores["b"].view(w.lst(), "iid-a")[0]
    to_d = w.stores["b"].view(w.lst(), "iid-d")[0]
    to_c = w.stores["b"].view(w.lst(), "iid-c")[0]
    assert f"panel:{name_key(5)}" in to_approved and "ops:auto_distribute" in to_approved
    assert f"panel:{name_key(5)}" in to_d and "ops:auto_distribute" in to_d
    assert not any(n.startswith("panel:") for n in to_c) and "status:iid-a" in to_c
    assert w.offer("c", {f"panel:{name_key(5)}": entry}, "b").accepted == 0


def test_authority_never_travels_as_a_record(world):
    assert set(kinds.KINDS) == {"status", "panel", "ops", "notify", "withhold", "workspace", "telemetry"}
    w = world(["a", "b", "c"])
    now = hlc.wall_ms()
    bad = {"roster:x": w.entry("a", "roster", "x", "v", now - 1000), "settings:master_install_id": w.entry("a", "settings", "master_install_id", "iid-a", now - 1000),
           "ops:reserve": w.entry("a", "ops", "reserve", 5, now - 1000)}
    out = w.offer("c", bad, "b")
    assert out.accepted == 0 and out.refused == 3
    assert not [n for n in w.stores["c"].servable(w.lst()) if n in bad]


def test_a_settled_pair_costs_nothing_until_something_changes_and_the_route_has_a_limit(world, monkeypatch):
    w = world(["a", "b", "c"])
    sent: List[int] = []

    class Quiet:

        async def request(self, method: str, path: str, json: Optional[dict] = None, **_kw: Any) -> Reply:
            sent.append(1)
            return Reply({"status": "ok", "records": {}})

    svc = gossip.Gossip(w.stores["a"], links_getter=lambda: None, signing=w.signing["a"], held_list=w.lst, label=lambda: "a", app_version="1.0", own_iid="iid-a",
                        members=lambda lst: [("iid-b", Quiet())])
    asyncio.run(svc.pass_once())
    first = len(sent)
    assert first >= 1 and svc.last_results["iid-b"] == "ok"
    asyncio.run(svc.pass_once())
    assert len(sent) == first and svc.last_results["iid-b"] == "settled"
    assert w.panel("a", name_key(6), "x")
    asyncio.run(svc.pass_once())
    assert len(sent) > first
    lst = w.lst()
    assert w.stores["a"].view(lst, "iid-b") is w.stores["a"].view(lst, "iid-c")
    clock = [0.0]
    monkeypatch.setattr(route, "_limiter", RateLimiter(limit=route.SYNC_RATE_LIMIT, window=60.0, clock=lambda: clock[0]))
    assert route.SYNC_RATE_LIMIT == 1200
    assert all(route._limiter.allow("iid-b") for _ in range(1200))  # noqa: SLF001
    monkeypatch.setattr("src.core.pack.machines.exchange.RUNTIME", SimpleNamespace(held_list=w.lst))
    monkeypatch.setattr(gossip, "ACTIVE", svc)
    principal = SimpleNamespace(is_peer=True, grant=SimpleNamespace(peer_install_id="iid-b"))
    answer = asyncio.run(route.post_sync(None, principal))  # type: ignore[arg-type]
    assert answer.status_code == 429 and json.loads(answer.body) == {"code": "rate_limited"} and answer.headers["cache-control"] == "no-store"
    clock[0] = 61.0
    assert route._limiter.allow("iid-b")  # noqa: SLF001


def test_production_opens_mesh_data_for_the_sync_alone():
    assert mesh_powers.MESH_DATA in mesh_powers.OPEN_POWERS
    assert mesh_powers.OPEN_POWERS == {mesh_powers.MESH_LINK, mesh_powers.MESH_LOGINS, mesh_powers.MESH_JOBS, mesh_powers.MESH_DATA}
    assert mesh_powers.power_for("POST", "/api/v1/federation/pack/mesh/sync") == mesh_powers.MESH_DATA
    assert mesh_powers.POWER_SCOPES[mesh_powers.MESH_DATA] == {"machine"}
    for method, path in (("POST", "/api/v1/federation/pack/exchange"), ("PUT", "/api/v1/federation/pack/labels"), ("POST", "/api/v1/federation/pack/rescan"),
                         ("GET", "/api/v1/stats/feed/local")):
        assert mesh_powers.power_for(method, path) is None, path
    assert mesh_powers.power_for("GET", "/api/v1/federation/pack/rollup") == mesh_powers.MESH_DATA
    assert sorted(row for row, power in mesh_powers.ROUTES.items() if power == mesh_powers.MESH_DATA) == [
        ("GET", "/api/v1/federation/pack/rollup"), ("POST", "/api/v1/federation/pack/mesh/sync")]


def test_a_caller_over_the_limit_costs_no_list_read_and_a_second_view_opens_no_connection(world, monkeypatch):
    w = world(["a", "b"])
    reads: List[int] = []
    monkeypatch.setattr(route, "_limiter", RateLimiter(limit=1, window=60.0, clock=lambda: 0.0))
    monkeypatch.setattr("src.core.pack.machines.exchange.RUNTIME", SimpleNamespace(held_list=lambda: reads.append(1) or w.lst()))
    monkeypatch.setattr(gossip, "ACTIVE", SimpleNamespace(store=w.stores["a"]))
    assert route._limiter.allow("iid-b")  # noqa: SLF001
    principal = SimpleNamespace(is_peer=True, grant=SimpleNamespace(peer_install_id="iid-b"))
    answer = asyncio.run(route.post_sync(None, principal))  # type: ignore[arg-type]
    assert answer.status_code == 429 and reads == []
    store, lst, opened = w.stores["a"], w.lst(), []
    real = store._connect  # noqa: SLF001
    monkeypatch.setattr(store, "_connect", lambda: opened.append(1) or real())
    store.view(lst, "iid-b")
    first = len(opened)
    assert first >= 1
    store.view(lst, "iid-b")
    store.view(lst, "iid-c")
    after_c = len(opened)
    store.view(lst, "iid-b")
    store.view(lst, "iid-c")
    assert len(opened) == after_c
    assert w.panel("a", name_key(1), "x")
    store.view(lst, "iid-b")
    assert len(opened) > after_c


def test_a_settled_entry_for_a_computer_off_the_list_is_pruned(world):
    w = world(["a", "b"])
    w.link([("a", "b")])
    svc = w.services["a"]
    svc._settled["iid-gone"] = ("d", 0.0)  # noqa: SLF001
    svc._settled["iid-b"] = ("d", 0.0)  # noqa: SLF001
    w.run("a")
    assert "iid-gone" not in svc._settled  # noqa: SLF001


def test_an_old_live_copy_below_a_collected_tombstone_earns_a_reasserted_delete_over_a_member_link(world):
    w = world(["a", "b", "c"])
    base = hlc.wall_ms()
    item = pin_key(7)
    live = w.entry("a", "panel", item, {"pos": "a1"}, base)
    tomb = w.entry("a", "panel", item, {"pos": None}, base + 1000)
    assert w.stores["b"].offer_batch({f"panel:{item}": live}, "iid-a", w.lst(), base).accepted == 1
    assert w.stores["c"].offer_batch({f"panel:{item}": tomb}, "iid-a", w.lst(), base).accepted == 1
    assert w.stores["c"].gc(base + panel_kind.TOMB_TTL_MS + 5000) == 1
    assert w.stores["c"].servable(w.lst()).get(f"panel:{item}") is None
    w.link([("b", "c")])
    w.run("b")
    with closing(w.stores["b"]._connect()) as conn:  # noqa: SLF001
        row = conn.execute("SELECT value_json, origin FROM records WHERE kind = 'panel' AND key = ?", (item,)).fetchone()
    assert row is not None and json_loads(row[0]) == {"pos": None} and row[1] == "iid-c"


def json_loads(text: str) -> Any:
    return json.loads(text)
