from __future__ import annotations

import asyncio
import json
import time
from contextlib import closing
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import pytest

from src.api import federation_pack_rollup_routes as routes
from src.core.computers import direction, mesh_removal
from src.core.notifications.sync.secrets_sync import RateLimiter
from src.core.pack.machines import capabilities as caps
from src.core.pack.meshdata import gossip
from src.core.pack.rollup_import import member_pull, puller, relay_export, relay_pull, relay_store, store
from src.core.pack.rollup_import.ddl import FLOOR_TABLE, STATE_TABLE, USAGE_TABLE
from tests.python.pack.test_mesh_notify import MeshApi, Registry
from tests.python.pack.test_rollup_import import _conversation, _source_totals
from tests.python.pack.test_rollup_relay import Node, _held
from tests.python.pack.test_rollup_signed_relay import Mesh, _noted, _relay_page

MEMBER_CAPS = [caps.CAP_MESH, caps.CAP_PIPELINE_ROLLUP, caps.CAP_ROLLUP_RELAY]
P1 = "p" * 24


class Reply:

    def __init__(self, status: int, body: Any) -> None:
        self.status_code, self._body = status, body

    def json(self) -> Any:
        return self._body


class Link:

    def __init__(self, caller: Node, target: Node, hook: Optional[Callable[[dict, dict], Optional[dict]]] = None, limiter: Optional[RateLimiter] = None,
                 withheld: frozenset = frozenset()) -> None:
        self.caller, self.target, self.hook, self.limiter, self.withheld, self.calls = caller, target, hook, limiter, withheld, 0

    async def request(self, method: str, path: str, json: Optional[dict] = None, **_kw: Any) -> Reply:
        self.calls += 1
        if self.limiter is not None and not self.limiter.allow(self.caller.iid):
            return Reply(429, {"code": "rate_limited"})
        q = {k: v[0] for k, v in parse_qs(urlparse(path).query).items()}
        page = relay_export.serve_stream(
            self.target, self.target.open_db, caller=self.caller.iid, stream=q.get("stream"), since_revision=int(q["since_rev"]),
            until_revision=int(q["until_rev"]) if "until_rev" in q else None, cursor=q.get("cursor"), max_bytes=int(q["max_bytes"]),
            signing=self.target.signing, withheld=self.withheld)
        page = json_roundtrip(page)
        return Reply(200, (self.hook(page, q) or page) if self.hook else page)


def json_roundtrip(page: dict) -> dict:
    return json.loads(json.dumps(page))


class Alpha:

    def __init__(self) -> None:
        self.calls = 0

    def post_for(self, _iid: str):
        async def post(*_a: Any, **_k: Any):
            self.calls += 1
            raise ConnectionError("alpha down")
        return post


@pytest.fixture()
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(caps, "MESH_BUILD_ON", True)
    monkeypatch.setattr(member_pull, "MEMBER_PAGE_GAP_SECONDS", 0)
    monkeypatch.setattr(member_pull, "_LAST", {})
    monkeypatch.setattr(direction, "contained", lambda iid: False)
    monkeypatch.setattr(direction, "listed_one_way", lambda lst, iid: False)
    from src.core.stats import config as stats_config
    monkeypatch.setattr(stats_config, "get_settings", lambda store: {"enabled": True})

    def build(*names: str) -> SimpleNamespace:
        mesh = Mesh(tmp_path, "z", *names)
        alpha = Alpha()
        for n in mesh.nodes.values():
            n.stats.commit()
            n.importer = puller.RollupImporter(n.open_db, alpha.post_for, lambda iid: [], n.clock, self_id=n.iid, held_list=mesh.roster)
        for n in names:
            mesh.nodes[n].pair(mesh.nodes["z"])
        return SimpleNamespace(mesh=mesh, alpha=alpha, **{n: mesh.nodes[n] for n in names})
    return build


def set_members(node: Node, members: List[str], live: Optional[List[str]] = None) -> None:
    node.importer.members = frozenset(members)
    node.importer.member_caps = {m: list(MEMBER_CAPS) for m in members}
    node.importer.live = frozenset(live if live is not None else members)


def member_pass(node: Node, links: Dict[str, Link]) -> None:
    node.clock.now += 61
    asyncio.run(member_pull.pull_once(node.importer, list(links.items())))


def floors(node: Node, origin: str) -> List[tuple]:
    with closing(node.open_db()) as conn:
        return sorted(tuple(r) for r in conn.execute(f"SELECT conversation_id, hour, floor FROM {FLOOR_TABLE} WHERE peer_install_id = ?", (origin,)).fetchall())


def supplier(node: Node, origin: str) -> Optional[str]:
    with closing(node.open_db()) as conn:
        row = conn.execute(f"SELECT via FROM {STATE_TABLE} WHERE peer_install_id = ?", (origin,)).fetchone()
    return None if row is None else row[0]


def chain(w: SimpleNamespace, b_hook=None, c_hook=None) -> Tuple[Dict[str, Link], Dict[str, Link]]:
    set_members(w.b, [w.a.iid, w.c.iid])
    set_members(w.c, [w.b.iid])
    return {w.a.iid: Link(w.b, w.a)}, {w.b.iid: Link(w.c, w.b, hook=c_hook)}


def seed_a(w: SimpleNamespace, seed: int = 1, hours=(0, 1, 2)) -> None:
    _conversation(w.a.stats, "conv-a", P1, list(hours), seed=seed)


def test_stats_reach_member_without_alpha(world):
    w = world("a", "b", "c")
    seed_a(w)
    b_links, c_links = chain(w)
    w.c.importer.members, w.c.importer.member_caps, w.c.importer.live = frozenset(), {}, None
    service = SimpleNamespace(member_pairs=lambda lst: [(w.b.iid, c_links[w.b.iid])])
    asyncio.run(member_pull.step(w.c.importer, star_ids=lambda: [], caps=lambda iid: MEMBER_CAPS)(service, w.mesh.roster()))
    assert w.c.importer.members == frozenset({w.b.iid}) and w.c.importer.live == frozenset({w.b.iid})
    member_pass(w.b, b_links)
    assert _held(w.b, w.a.iid) == _source_totals(w.a.stats) and supplier(w.b, w.a.iid) == ""
    member_pass(w.c, c_links)
    assert _held(w.c, w.a.iid) == _source_totals(w.a.stats) and _held(w.c, w.a.iid)[0] > 0
    assert supplier(w.c, w.a.iid) == w.b.iid and w.alpha.calls == 0
    with closing(w.c.open_db()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM pack_rollup_rev WHERE peer_install_id = ? AND sig IS NOT NULL AND origin_rev IS NOT NULL", (w.a.iid,)).fetchone()[0] == 3


def test_forged_origin_refused(world):
    w = world("a", "b", "c")
    seed_a(w)
    b_links, c_links = chain(w)
    member_pass(w.b, b_links)
    before = floors(w.c, w.a.iid)
    with closing(w.b.open_db()) as conn:
        conn.execute(f"UPDATE {USAGE_TABLE} SET input = input + 1 WHERE peer_install_id = ?", (w.a.iid,))
        conn.commit()
    member_pass(w.c, c_links)
    assert _held(w.c, w.a.iid) == (0, 0, 0) and _noted(w.c, "relay_forged") and floors(w.c, w.a.iid) == before
    with closing(w.b.open_db()) as conn:
        conn.execute(f"UPDATE {USAGE_TABLE} SET input = input - 1 WHERE peer_install_id = ?", (w.a.iid,))
        conn.commit()
    from src.core.pack.meshdata import envelope
    from src.core.pack.rollup_import import signed

    def resign(page: dict, q: dict) -> Optional[dict]:
        for group in page.get("groups", []):
            body = signed.wire_body(group)
            forged = envelope.sign(envelope.KIND_ROLLUP, signed.group_key(body[0], body[1]), group["orev"], envelope.body_hash(body[2]), w.b.signing)
            group["sig"] = {"signer": w.a.iid, "sig": forged.sig}
        return page

    w.c.importer._noted.clear()
    c_links[w.b.iid].hook = resign
    member_pass(w.c, c_links)
    assert _held(w.c, w.a.iid) == (0, 0, 0) and _noted(w.c, "relay_forged") and floors(w.c, w.a.iid) == before


def test_replayed_older_revision_refused(world):
    w = world("a", "b", "c")
    seed_a(w, seed=1, hours=(1,))
    b_links, c_links = chain(w)
    member_pass(w.b, b_links)
    member_pass(w.c, c_links)
    old = _relay_page(w.mesh, w.c, w.b)
    seed_a(w, seed=9, hours=(1,))
    member_pass(w.b, b_links)
    member_pass(w.c, c_links)
    held = _held(w.c, w.a.iid)
    assert held == _source_totals(w.a.stats)
    floor = floors(w.c, w.a.iid)
    c_links[w.b.iid].hook = lambda page, q: json_roundtrip(old) if q.get("stream") == "relay" else None
    member_pass(w.c, c_links)
    assert _held(w.c, w.a.iid) == held and floors(w.c, w.a.iid) == floor and not _noted(w.c, "relay_forged")


def test_removed_origin_refused(world):
    w = world("a", "b", "c")
    seed_a(w)
    b_links, c_links = chain(w)
    member_pass(w.b, b_links)
    member_pass(w.c, c_links)
    assert _held(w.c, w.a.iid)[0] > 0
    w.mesh.listed = [n for n in w.mesh.listed if n != "a"]
    seed_a(w, seed=5, hours=(1, 6))
    with closing(w.c.open_db()) as conn:
        assert mesh_removal.purge_local(conn, w.a.iid) is True
    assert _held(w.c, w.a.iid) == (0, 0, 0) and floors(w.c, w.a.iid)
    member_pass(w.c, c_links)
    assert _held(w.c, w.a.iid) == (0, 0, 0) and supplier(w.c, w.a.iid) is None


def test_on_demand_never_pulled(world):
    w = world("a", "b", "c")
    lst = w.mesh.roster()
    from src.core.computers import mesh_choice  # noqa: F401
    link = Link(w.b, w.c)
    reg = Registry([(w.c.iid, link)])
    api = MeshApi(lst)
    standing = gossip.member_links(lst, w.b.iid, reg, api)
    assert [i for i, _ in standing] == [w.c.iid]
    api.on_demand = lambda iid: True
    pairs = gossip.member_links(lst, w.b.iid, reg, api)
    assert pairs == []
    set_members(w.b, [])
    asyncio.run(member_pull.pull_once(w.b.importer, pairs))
    assert link.calls == 0


def _seed_supplier(node: Node, origin: Node, via: Node, revision: int, offers: List[Node]) -> None:
    with closing(node.open_db()) as conn:
        assert store.finish(conn, origin.iid, revision, "d", 1.0, via=via.iid, hops=2, members=node.importer.members)
        for forwarder in offers:
            relay_store.record_offers(conn, forwarder.iid, {origin.iid: 1}, 1.0)
        conn.commit()


def test_sticky_supplier(world):
    w = world("a", "b", "c")
    set_members(w.c, [w.b.iid], live=[w.b.iid])
    _seed_supplier(w.c, w.a, w.mesh.nodes["z"], 10, [w.mesh.nodes["z"], w.b])
    pick = lambda conn, **kw: relay_store.choose_supplier(conn, w.a.iid, lambda i: False, members=w.c.importer.members, live=w.c.importer.live, **kw)
    with closing(w.c.open_db()) as conn:
        assert pick(conn, offer=(w.b.iid, {"revision": 10})) == ("iid-z", 2)
        assert pick(conn, offer=(w.b.iid, {"revision": 11})) == (w.b.iid, 2)
        assert relay_store.choose_supplier(conn, w.a.iid, lambda i: False) == ("iid-z", 2)
    with closing(w.c.open_db()) as conn:
        store.reset_origin(conn, w.a.iid, "d", 2.0, via=w.b.iid, hops=2, members=w.c.importer.members)
        store.finish(conn, w.a.iid, 10, "d", 2.0, via=w.b.iid, hops=2, members=w.c.importer.members)
        conn.commit()
    imp = w.c.importer
    imp.live = frozenset({w.b.iid, "iid-z"})
    header = {w.a.iid: {"hops": 1, "revision": 11}}
    with closing(w.c.open_db()) as conn:
        relay_pull._note_behind(imp, conn, "iid-z", header, imp._clock())
        t0 = imp.behind[w.a.iid][0]
        assert relay_pull._pick(imp, conn, "iid-z", w.a.iid, header, t0 + relay_pull.STALE_SECONDS - 1) == (w.b.iid, 2)
        assert relay_pull._pick(imp, conn, "iid-z", w.a.iid, header, t0 + relay_pull.STALE_SECONDS) == ("iid-z", 2)
        imp._busy.add(w.b.iid)
        assert relay_pull._pick(imp, conn, "iid-z", w.a.iid, header, t0 + relay_pull.STALE_SECONDS + 5) == (w.b.iid, 2)
        imp._busy.discard(w.b.iid)


class FakeClock:

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


def _cut(pages: int):
    def serve(q: dict) -> dict:
        k = int(q["cursor"][1:]) + 1 if q.get("cursor") else 0
        return {"available": True, "scope_digest": "d", "groups": [], "until_revision": 5, "complete": k == pages - 1, "next_cursor": f"c{k}", "stream": None}
    return serve


class Cut(Link):

    def __init__(self, caller: Node, limiter: RateLimiter, pages: int) -> None:
        super().__init__(caller, caller, limiter=limiter)
        self.serve = _cut(pages)

    async def request(self, method: str, path: str, json: Optional[dict] = None, **_kw: Any) -> Reply:
        self.calls += 1
        if not self.limiter.allow(self.caller.iid):
            return Reply(429, {"code": "rate_limited"})
        return Reply(200, self.serve({k: v[0] for k, v in parse_qs(urlparse(path).query).items()}))


def test_long_pull_no_livelock(world, monkeypatch):
    w = world("b", "c")
    clock = FakeClock()
    monkeypatch.setattr(member_pull, "MEMBER_PAGE_GAP_SECONDS", 0.75)
    monkeypatch.setattr(member_pull, "_clock", clock)
    monkeypatch.setattr(member_pull, "_sleep", clock.sleep)
    limiter = RateLimiter(limit=routes.ROLLUP_MEMBER_RATE_LIMIT, window=60.0, clock=clock)
    c, b = w.c, w.b
    c.importer.members, c.importer.live = frozenset({b.iid}), frozenset({b.iid})
    c.importer.member_caps = {b.iid: [caps.CAP_MESH, caps.CAP_PIPELINE_ROLLUP]}

    def state_rev() -> Optional[int]:
        with closing(c.open_db()) as conn:
            row = conn.execute(f"SELECT revision FROM {STATE_TABLE} WHERE peer_install_id = ?", (b.iid,)).fetchone()
        return None if row is None else row[0]

    clean = Cut(c, limiter, 400)
    member_pass(c, {b.iid: clean})
    assert clean.calls == 400 and state_rev() == 5 and not _noted(c, "unavailable")
    with closing(c.open_db()) as conn:
        conn.execute(f"DELETE FROM {STATE_TABLE}")
        conn.commit()
    limiter._hits.clear()
    for _ in range(routes.ROLLUP_MEMBER_RATE_LIMIT - 1):
        limiter.allow(c.iid)
    clock.now += 0.1
    limited = Cut(c, limiter, 400)
    member_pass(c, {b.iid: limited})
    assert 0 < limited.calls < 400 and state_rev() is None and _noted(c, "unavailable")
    clock.now += 61
    again = Cut(c, limiter, 400)
    member_pass(c, {b.iid: again})
    assert again.calls == 400 and state_rev() == 5


def test_stripped_one_way_cannot_widen(world, monkeypatch):
    w = world("a", "b", "c", "x")
    seed_a(w)
    b_links, c_links = chain(w)
    member_pass(w.b, b_links)
    lst = w.mesh.roster()
    with closing(w.b.open_db()) as conn:
        conn.execute(f"UPDATE {STATE_TABLE} SET one_way = ? WHERE peer_install_id = ?", (json.dumps([w.mesh.nodes["x"].iid]), w.a.iid))
        conn.commit()
    unstripped = relay_export.serve_stream(w.b, w.b.open_db, caller="iid-x", stream="relay", since_revision=0, max_bytes=524288, signing=w.b.signing)
    assert w.a.iid not in unstripped["origins"]
    with closing(w.b.open_db()) as conn:
        conn.execute(f"UPDATE {STATE_TABLE} SET one_way = '[]' WHERE peer_install_id = ?", (w.a.iid,))
        conn.commit()
    widened = relay_export.serve_stream(w.b, w.b.open_db, caller="iid-x", stream="relay", since_revision=0, max_bytes=524288, signing=w.b.signing)
    assert w.a.iid in widened["origins"]
    class Withhold:
        def withholding(self, _lst: Any, peer: str) -> frozenset:
            return frozenset({w.a.iid}) if peer == "iid-x" else frozenset()
    held_by_c = Withhold().withholding(lst, "iid-x")
    closed = relay_export.serve_stream(w.b, w.b.open_db, caller="iid-x", stream="relay", since_revision=0, max_bytes=524288, signing=w.b.signing, withheld=held_by_c)
    assert w.a.iid not in closed["origins"] and not any(g["origin"] == w.a.iid for g in closed["groups"])
    before = _held(w.b, w.a.iid)
    with closing(w.b.open_db()) as conn:
        conn.execute(f"UPDATE {STATE_TABLE} SET label = 'renamed' WHERE peer_install_id = ?", (w.a.iid,))
        conn.commit()
    member_pass(w.c, c_links)
    assert _held(w.b, w.a.iid) == before and _held(w.c, w.a.iid) == _source_totals(w.a.stats)


def test_the_unsigned_stream_is_filtered_by_a_withhold_too(world):
    w = world("a", "b", "c", "x")
    seed_a(w)
    b_links, _c_links = chain(w)
    member_pass(w.b, b_links)
    open_page = relay_export.serve_stream(w.b, w.b.open_db, caller="iid-x", stream="relay", since_revision=0, max_bytes=524288, signing=None)
    assert w.a.iid in open_page["origins"]
    closed = relay_export.serve_stream(w.b, w.b.open_db, caller="iid-x", stream="relay", since_revision=0, max_bytes=524288, signing=None, withheld=frozenset({w.a.iid}))
    assert w.a.iid not in closed["origins"] and not any(g["origin"] == w.a.iid for g in closed["groups"])


def test_the_route_filters_an_unsigned_star_caller_by_the_withhold_set(world, monkeypatch):
    w = world("a", "b", "c", "x")
    seed_a(w)
    b_links, _c_links = chain(w)
    member_pass(w.b, b_links)
    monkeypatch.setattr(routes.peer_auth, "open_db", w.b.open_db)
    page = dict(stream="relay", since_revision=0, until_revision=None, cursor=None, max_bytes=524288)
    monkeypatch.setattr(routes, "_withheld_from", lambda caller: frozenset())
    control = routes._serve(w.b, "iid-x", None, **page)
    assert w.a.iid in control["origins"]
    monkeypatch.setattr(routes, "_withheld_from", lambda caller: frozenset({w.a.iid}) if caller == "iid-x" else frozenset())
    closed = routes._serve(w.b, "iid-x", None, **page)
    assert w.a.iid not in closed["origins"] and not any(g["origin"] == w.a.iid for g in closed["groups"])


def test_one_way_computer(world, monkeypatch):
    w = world("b", "x")
    lst = w.mesh.roster()
    reg = Registry([(w.b.iid, Link(w.mesh.nodes["x"], w.b)), (w.mesh.nodes["x"].iid, Link(w.b, w.mesh.nodes["x"]))])
    api = MeshApi(lst)
    assert gossip.member_links(lst, w.b.iid, reg, api) != []
    xid = w.mesh.nodes["x"].iid
    monkeypatch.setattr(direction, "listed_one_way", lambda l, iid: iid == xid)
    assert gossip.member_links(lst, xid, reg, api) == []
    assert xid not in [i for i, _ in gossip.member_links(lst, w.b.iid, reg, api)]


def test_route_limit_is_per_member_caller_and_star_never_touches_it(monkeypatch):
    from src.core.federation.mesh_grants import MeshGrant
    from src.core.federation.grants import Grant
    limiter = RateLimiter(limit=1, window=60.0)
    monkeypatch.setattr(routes, "_member_limiter", limiter)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(stats_store=None)))

    def principal(grant: Any) -> Any:
        return SimpleNamespace(is_peer=True, grant=grant)

    def call(grant: Any) -> Any:
        try:
            return asyncio.run(routes.get_rollup(request, 0, None, None, 4096, None, principal(grant)))
        except Exception as exc:  # noqa: BLE001
            return getattr(exc, "detail", exc)
    def member(iid: str) -> MeshGrant:
        return MeshGrant("g", iid, "k", "f", "l", (), None, "t", None, None)
    assert call(member("iid-x")) == {"code": "stats_unavailable"}
    second = call(member("iid-x"))
    assert second.status_code == 429 and json.loads(second.body) == {"code": "rate_limited"}
    assert call(member("iid-y")) == {"code": "stats_unavailable"}
    monkeypatch.setattr(routes, "_member_limiter", SimpleNamespace(allow=lambda key: (_ for _ in ()).throw(AssertionError("star touched the limiter"))))
    star = Grant("g", "iid-s", "k", "f", "l", ("machine",), None, "t", None, None)
    assert call(star) == {"code": "stats_unavailable"}


def test_switch_off_identical(world, monkeypatch):
    w = world("a", "b")
    monkeypatch.setattr(caps, "MESH_BUILD_ON", False)
    with closing(w.b.open_db()) as conn:
        assert relay_store.supplier_ok(conn, w.a.iid, frozenset({w.a.iid})) is False
        assert relay_store.supplier_ok(conn, "iid-z", frozenset()) is True
        assert store.reset_origin(conn, w.a.iid, "d", 1.0, members=frozenset({w.a.iid})) is False
        assert relay_store.choose_supplier(conn, w.a.iid, lambda i: False, members=frozenset({w.a.iid}), live=frozenset({w.a.iid})) is None
    w.b.importer.member_caps = {w.a.iid: MEMBER_CAPS}
    asyncio.run(w.b.importer.maybe_pull_member(w.a.iid, Link(w.b, w.a).request))
    assert not w.b.importer._busy and (w.a.iid, "member_unsigned") in w.b.importer._noted
    assert w.b.importer._caps_for(w.a.iid) == [] and w.b.importer.live is None
    src = open(puller.__file__.replace("rollup_import/puller.py", "machines/runtime.py")).read()
    assert src.index("member_pull.step") > src.index("if caps_mod.mesh_on():")


def test_a_member_link_with_no_signing_is_refused_never_served_the_unsigned_stream(monkeypatch):
    from src.core.federation.mesh_grants import MeshGrant
    from src.core.pack.machines import exchange
    monkeypatch.setattr(caps, "MESH_BUILD_ON", True)
    monkeypatch.setattr(exchange, "RUNTIME", None)
    grant = MeshGrant("g", "iid-x", "k", "f", "l", (), None, "t", None, None)
    with pytest.raises(Exception) as refused:
        routes._signing_for(grant)
    assert refused.value.status_code == 503 and refused.value.detail == {"code": "stats_unavailable"}
    monkeypatch.setattr(exchange, "RUNTIME", SimpleNamespace(custody=SimpleNamespace(signing=None)))
    with pytest.raises(Exception) as refused:
        routes._signing_for(grant)
    assert refused.value.status_code == 503
    monkeypatch.setattr(caps, "MESH_BUILD_ON", False)
    assert routes._signing_for(grant) is None


def test_a_list_change_drops_a_removed_computer_from_the_importer_at_once(world):
    w = world("a", "b", "c")
    lst = w.mesh.roster()
    set_members(w.b, [w.a.iid, w.c.iid], live=[w.a.iid, w.c.iid, "iid-star"])
    member_pull._PAIRS[:] = [(w.a.iid, object()), (w.c.iid, object())]
    try:
        member_pull.on_list(w.b.importer, lst, w.b.iid)
        assert w.b.importer.members == frozenset({w.a.iid, w.c.iid})
        gone = lst.model_copy(update={"computers": [c for c in lst.computers if c.install_id != w.c.iid]})
        member_pull.on_list(w.b.importer, gone, w.b.iid)
        assert w.b.importer.members == frozenset({w.a.iid}) and set(w.b.importer.member_caps) == {w.a.iid}
        assert w.b.importer.live == frozenset({w.a.iid, "iid-star"}) and [i for i, _ in member_pull._PAIRS] == [w.a.iid]
    finally:
        member_pull._PAIRS[:] = []
