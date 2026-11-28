from __future__ import annotations

import asyncio
import base64
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import pytest

from src.core.federation import peer_hosts
from src.core.pack.machines import capabilities as caps
from src.core.pack.machines.roster_v2 import RosterComputerV2, RosterV2
from src.core.pack.machines.settings_sign import Signing
from src.core.pack.meshdata import envelope
from src.core.pack.rollup_import import puller, relay_export, relay_store, signed, store
from src.core.pack.rollup_import.ddl import EPOCH_FLOOR_KEY, FLOOR_TABLE, META_TABLE, PROJECTS_TABLE, REV_TABLE, STATE_TABLE, USAGE_TABLE
from src.core.relay_identity.device_key import DeviceKey, b64url
from src.core.stats import config as stats_config, rollup
from src.core.stats.plugin.extract import project_key
from tests.python.pack.test_rollup_import import Clock, _conversation, _source_totals, _stats_db
from tests.python.pack.test_rollup_relay import CAPS, Node, _held

MESH_CAPS = [*CAPS, caps.CAP_MESH]
CERT = base64.b64encode(b"x" * 40).decode()


class Mesh:

    def __init__(self, tmp: Path, *names: str) -> None:
        self.nodes: Dict[str, Node] = {}
        self.keys: Dict[str, DeviceKey] = {}
        self.listed = list(names)
        for i, name in enumerate(names):
            node = Node(tmp, name)
            self.keys[name] = DeviceKey.from_seed(bytes([i + 7]) * 32)
            node.signing = Signing(install_id=node.iid, load_key=lambda n=name: self.keys[n], pinned_key=lambda iid: None)
            self.nodes[name] = node

    def roster(self) -> RosterV2:
        rows = [RosterComputerV2(install_id=f"iid-{n}", label=n, fed_public_key=b64url(self.keys[n].raw_pub), cert=CERT, mesh=True) for n in self.listed]
        return RosterV2(generation=1, alpha=rows[0].install_id, home=rows[0].install_id, issued_at=1, computers=rows)

    def wire(self, name: str, node_caps=MESH_CAPS) -> Node:
        node = self.nodes[name]
        node.importer = puller.RollupImporter(node.open_db, lambda iid, node=node: self.post(node, self.by_iid(iid)), lambda iid: node_caps, node.clock,
                                              self_id=node.iid, held_list=self.roster)
        return node

    def by_iid(self, iid: str) -> Node:
        return next(n for n in self.nodes.values() if n.iid == iid)

    def post(self, caller: Node, target: Node):
        async def post(method: str, path: str, body: Optional[dict]) -> Tuple[int, Any]:
            q = {k: v[0] for k, v in parse_qs(urlparse(path).query).items()}
            page = relay_export.serve_stream(
                target, target.open_db, caller=caller.iid, stream=q.get("stream"), since_revision=int(q["since_rev"]),
                until_revision=int(q["until_rev"]) if "until_rev" in q else None, cursor=q.get("cursor"), max_bytes=int(q["max_bytes"]),
                signing=target.signing if caps.mesh_on() else None)
            return 200, json.loads(json.dumps(page))
        return post


@pytest.fixture()
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(stats_config, "get_settings", lambda store: {"enabled": True})
    monkeypatch.setattr(caps, "MESH_BUILD_ON", True)

    def build(*names: str) -> Mesh:
        mesh = Mesh(tmp_path, *names)
        for name in names:
            mesh.wire(name)
        return mesh
    return build


def _noted(node: Node, why: str) -> bool:
    return any(reason == why for _peer, reason in node.importer._noted)


def test_a_signed_group_lands_and_a_forwarder_cannot_alter_or_impersonate(world, tmp_path):
    mesh = world("a", "b", "c", "d")
    a, b, c, d = (mesh.nodes[n] for n in "abcd")
    b.pair(a)
    c.pair(b)
    d.pair(b)
    root = str(tmp_path / "carnivore")
    with closing(a.open_db()) as conn:
        conn.execute("INSERT INTO projects (root, raw_path, display_name, source, created_at, updated_at) VALUES (?, ?, 'carnivore', 'manual', 'now', 'now')", (root, root))
    _conversation(a.stats, "conv-a", project_key(root), [0, 1, 2], seed=1)

    b.pull(a)
    with closing(b.open_db()) as conn:
        assert conn.execute(f"SELECT COUNT(*) FROM {REV_TABLE} WHERE peer_install_id = ? AND sig IS NOT NULL AND origin_rev IS NOT NULL", (a.iid,)).fetchone()[0] == 3
        assert relay_store.names_proof(conn, a.iid) is not None
    c.pull(b)
    assert _held(c, a.iid) == _source_totals(a.stats) and _held(c, a.iid)[0] > 0
    with closing(c.open_db()) as conn:
        assert conn.execute(f"SELECT name FROM {PROJECTS_TABLE} WHERE peer_install_id = ? AND project = ?", (a.iid, project_key(root))).fetchone()[0] == "carnivore"
        assert relay_store.names_proof(conn, a.iid) is not None

    with closing(b.open_db()) as conn:
        conn.execute(f"UPDATE {USAGE_TABLE} SET input = input + 1 WHERE peer_install_id = ?", (a.iid,))
        conn.commit()
    d.pull(b)
    assert _held(d, a.iid) == (0, 0, 0) and _noted(d, "relay_forged")

    with closing(b.open_db()) as conn:
        conn.execute(f"UPDATE {USAGE_TABLE} SET input = input - 1 WHERE peer_install_id = ?", (a.iid,))
        conn.commit()
    real = mesh.post(d, b)

    async def forging_post(method: str, path: str, body: Optional[dict]) -> Tuple[int, Any]:
        status, page = await real(method, path, body)
        for group in page.get("groups", []):
            body_of = signed.wire_body({**group, "usage": group["usage"], "counters": group["counters"]})
            forged = envelope.sign(envelope.KIND_ROLLUP, signed.group_key(body_of[0], body_of[1]), group["orev"], envelope.body_hash(body_of[2]), b.signing)
            group["sig"] = {"signer": a.iid, "sig": forged.sig}
        return status, page

    d.importer._post_for = lambda iid: forging_post
    d.importer._noted.clear()
    d.pull(b)
    assert _held(d, a.iid) == (0, 0, 0) and _noted(d, "relay_forged")


def test_a_replayed_older_revision_is_skipped(world, monkeypatch):
    events: list = []
    monkeypatch.setattr(store, "logger", type("Spy", (), {"warning": staticmethod(lambda event, **kw: events.append(event))})())
    mesh = world("a", "b")
    a, b = mesh.nodes["a"], mesh.nodes["b"]
    b.pair(a)
    _conversation(a.stats, "conv-a", "a" * 24, [0, 1], seed=1)
    old = asyncio.run(mesh.post(b, a)("GET", f"{puller.ROLLUP_PATH}?since_rev=0&max_bytes=524288&stream=own", None))[1]
    b.pull(a)
    _conversation(a.stats, "conv-a", "a" * 24, [1, 5], seed=9)
    b.pull(a)
    held = _held(b, a.iid)
    assert held == _source_totals(a.stats)

    async def stale(method: str, path: str, body: Optional[dict]) -> Tuple[int, Any]:
        return 200, old

    b.importer._post_for = lambda iid: stale
    b.clock.now += 61
    asyncio.run(b.importer.maybe_pull(a.iid, {"install_id": a.iid, "pipeline_rev": {"stats": 10 ** 15}}))
    assert _held(b, a.iid) == held, "the older signed groups did not replace the newer rows"
    assert "pack_rollup_groups_replayed" in events and not _noted(b, "forged"), "the replay-skip path ran; the page was not refused as forged"


def test_a_computer_removed_from_the_list_is_refused(world):
    mesh = world("a", "b", "c")
    a, b, c = (mesh.nodes[n] for n in "abc")
    b.pair(a)
    c.pair(b)
    _conversation(a.stats, "conv-a", "a" * 24, [0, 1], seed=1)
    b.pull(a)
    c.pull(b)
    before = _held(c, a.iid)
    assert before[0] > 0
    mesh.listed = ["b", "c"]
    _conversation(a.stats, "conv-a", "a" * 24, [1, 6], seed=5)
    b.pull(a)
    assert _noted(b, "forged") and _held(b, a.iid) == before, "A's new groups are refused on a direct pull"
    with closing(c.open_db()) as conn:
        assert relay_store.origins_via(conn, b.iid) == [a.iid]
    c.pull(b)
    assert _held(c, a.iid) == before


def test_unpairing_one_forwarder_keeps_the_other_supplying(world):
    mesh = world("a", "b1", "b2", "c")
    a, b1, b2, c = (mesh.nodes[n] for n in ("a", "b1", "b2", "c"))
    b1.pair(a)
    b2.pair(a)
    c.pair(b1, b2)
    _conversation(a.stats, "conv-a", "a" * 24, [0, 1], seed=1)
    b1.pull(a)
    b2.pull(a)
    c.pull(b1)
    c.pull(b2)
    assert _held(c, a.iid)[0] > 0
    with closing(c.open_db()) as conn:
        assert conn.execute(f"SELECT via FROM {STATE_TABLE} WHERE peer_install_id = ?", (a.iid,)).fetchone()[0] == b1.iid
        peer_hosts.delete(conn, b1.iid)
        assert [r[0] for r in conn.execute("SELECT forwarder_install_id FROM pack_rollup_offers WHERE origin_install_id = ?", (a.iid,))] == [b2.iid]
        assert relay_store.get_relay_state(conn, b2.iid)[0] == 0
    assert _held(c, a.iid) == (0, 0, 0)
    c.pull(b2)
    assert _held(c, a.iid) == _source_totals(a.stats)


def test_a_forwarder_reset_sends_delete_orders_downstream(world, monkeypatch):
    monkeypatch.setattr(caps, "MESH_BUILD_ON", False)
    mesh = world("a", "b", "c", "d")
    a, b, c, d = (mesh.nodes[n] for n in "abcd")
    for node in mesh.nodes.values():
        node.importer = puller.RollupImporter(node.open_db, lambda iid, node=node: mesh.post(node, mesh.by_iid(iid)), lambda iid: CAPS, node.clock, self_id=node.iid)
    b.pair(a)
    c.pair(b)
    d.pair(c)
    hidden = "x" * 24
    _conversation(a.stats, "conv-ok", "a" * 24, [0, 1], seed=1)
    _conversation(a.stats, "conv-hidden", hidden, [0, 1], seed=2)
    b.pull(a)
    c.pull(b)
    d.pull(c)
    with closing(d.open_db()) as conn:
        assert conn.execute(f"SELECT COUNT(*) FROM {USAGE_TABLE} WHERE peer_install_id = ? AND project = ?", (a.iid, hidden)).fetchone()[0] > 0
    monkeypatch.setattr(rollup, "withheld_keys", lambda store: frozenset({hidden}) if store is b else frozenset())
    _conversation(a.stats, "conv-new", "a" * 24, [3], seed=3)
    b.pull(a)
    c.pull(b)
    d.pull(c)
    with closing(d.open_db()) as conn:
        assert conn.execute(f"SELECT COUNT(*) FROM {USAGE_TABLE} WHERE peer_install_id = ? AND project = ?", (a.iid, hidden)).fetchone()[0] == 0
        assert conn.execute(f"SELECT COUNT(*) FROM {USAGE_TABLE} WHERE peer_install_id = ? AND project != ?", (a.iid, hidden)).fetchone()[0] > 0


def test_a_withheld_projects_name_is_not_relayed_and_names_are_capped(world, monkeypatch):
    monkeypatch.setattr(caps, "MESH_BUILD_ON", False)
    mesh = world("a", "b")
    b = mesh.nodes["b"]
    with closing(b.open_db()) as conn:
        conn.execute(f"INSERT INTO {PROJECTS_TABLE} (peer_install_id, project, name, home_install_id) VALUES ('iid-a', 'secret', 'secret project', NULL), ('iid-a', 'open', 'open project', NULL)")
        names, _homes = relay_export._names(conn, ["iid-a"], frozenset({"secret"}))
        assert names == {"iid-a": {"open": "open project"}}
        stored = relay_store.replace_names(conn, "iid-a", {f"k{i}": f"n{i}" for i in range(relay_store.MAX_NAMES + 500)}, {})
    assert stored == relay_store.MAX_NAMES


def test_with_the_switch_off_the_wire_is_unchanged(world, monkeypatch):
    monkeypatch.setattr(caps, "MESH_BUILD_ON", False)
    mesh = world("a", "b")
    a = mesh.nodes["a"]
    _conversation(a.stats, "conv-a", "a" * 24, [0], seed=1)
    plain = relay_export.serve_stream(a, a.open_db, caller="iid-b", stream="own", since_revision=0, max_bytes=rollup.PAGE_BYTES)
    asked = relay_export.serve_stream(a, a.open_db, caller="iid-b", stream="own", since_revision=0, max_bytes=rollup.PAGE_BYTES, signing=a.signing)
    assert plain == asked and "." not in plain["scope_digest"] and all("sig" not in g for g in plain["groups"])
    assert not envelope.verify(envelope.KIND_ROLLUP, "iid-a", "k", 1, "h", None, mesh.roster())


P1, P2 = "p" * 24, "q" * 24


def _project_rows(node: Node, origin: str, project: str) -> int:
    with closing(node.open_db()) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {USAGE_TABLE} WHERE peer_install_id = ? AND project = ?", (origin, project)).fetchone()[0]


def _air_gap(monkeypatch, origin: Node, allow: Optional[frozenset]) -> None:
    monkeypatch.setattr(rollup, "allowed_projects", lambda store: allow if store is origin else None)


def _relay_page(mesh: Mesh, caller: Node, target: Node) -> dict:
    return asyncio.run(mesh.post(caller, target)("GET", f"{puller.ROLLUP_PATH}?since_rev=0&max_bytes=524288&stream=relay", None))[1]


def _replay(node: Node, supplier: Node, page: dict, stream: str) -> None:
    async def stale(method: str, path: str, body: Optional[dict]) -> Tuple[int, Any]:
        return 200, json.loads(json.dumps(page))

    real = node.importer._post_for
    node.importer._post_for = lambda iid: stale
    node.clock.now += 61
    asyncio.run(node.importer.maybe_pull(supplier.iid, {"install_id": supplier.iid, "pipeline_rev": {stream: 10 ** 15}}))
    node.importer._post_for = real


def test_a_replay_through_release_then_purge_is_refused(world):
    mesh = world("a", "b", "c")
    a, b, c = (mesh.nodes[n] for n in "abc")
    b.pair(a)
    c.pair(b)
    _conversation(a.stats, "conv-a", P1, [1], seed=1)
    b.pull(a)
    c.pull(b)
    old = _relay_page(mesh, c, b)
    _conversation(a.stats, "conv-a", P1, [1], seed=9)
    b.pull(a)
    c.pull(b)
    assert _held(c, a.iid) == _source_totals(a.stats)
    with closing(b.open_db()) as conn:
        conn.execute(f"DELETE FROM {STATE_TABLE} WHERE peer_install_id = ?", (a.iid,))
        conn.execute(f"UPDATE {META_TABLE} SET v = v + 1 WHERE k = 'relay_rev'")
        conn.commit()
    c.pull(b)
    assert _held(c, a.iid) == (0, 0, 0)
    with closing(c.open_db()) as conn:
        assert conn.execute(f"SELECT COUNT(*) FROM {FLOOR_TABLE} WHERE peer_install_id = ?", (a.iid,)).fetchone()[0] > 0, "the release kept the floors"
    _replay(c, b, old, "relay")
    assert _held(c, a.iid) == (0, 0, 0) and not _noted(c, "relay_forged"), "the older groups were skipped as replays, not stored"
    with closing(c.open_db()) as conn:
        peer_hosts.delete(conn, b.iid)
        assert conn.execute(f"SELECT COUNT(*) FROM {FLOOR_TABLE} WHERE peer_install_id = ?", (a.iid,)).fetchone()[0] > 0


def test_an_equal_stamp_older_body_is_refused_once_the_epoch_moved(world, monkeypatch):
    mesh = world("a", "b")
    a, b = mesh.nodes["a"], mesh.nodes["b"]
    b.pair(a)
    _conversation(a.stats, "conv-ok", P1, [0, 1], seed=1)
    _conversation(a.stats, "conv-hid", P2, [0, 1], seed=2)
    old = asyncio.run(mesh.post(b, a)("GET", f"{puller.ROLLUP_PATH}?since_rev=0&max_bytes=524288&stream=own", None))[1]
    b.pull(a)
    assert _project_rows(b, a.iid, P2) > 0
    _air_gap(monkeypatch, a, frozenset({P1}))
    _conversation(a.stats, "conv-new", P1, [3], seed=3)
    b.pull(a)
    assert _project_rows(b, a.iid, P2) == 0 and _project_rows(b, a.iid, P1) > 0
    with closing(b.open_db()) as conn:
        held_epoch = conn.execute(f"SELECT floor FROM {FLOOR_TABLE} WHERE peer_install_id = ? AND conversation_id = ?", (a.iid, EPOCH_FLOOR_KEY)).fetchone()[0]
        assert conn.execute(f"SELECT floor FROM {FLOOR_TABLE} WHERE peer_install_id = ? AND conversation_id = 'conv-hid'", (a.iid,)).fetchone()[0] >= 0
    _replay(b, a, old, "stats")
    assert _project_rows(b, a.iid, P2) == 0 and not _noted(b, "forged")
    with closing(b.open_db()) as conn:
        assert conn.execute(f"SELECT floor FROM {FLOOR_TABLE} WHERE peer_install_id = ? AND conversation_id = ?", (a.iid, EPOCH_FLOOR_KEY)).fetchone()[0] == held_epoch


def test_the_drop_reaches_a_second_hop_and_a_forwarder_cannot_fake_an_epoch(world, monkeypatch):
    mesh = world("a", "b", "c")
    a, b, c = (mesh.nodes[n] for n in "abc")
    b.pair(a)
    c.pair(b)
    _conversation(a.stats, "conv-ok", P1, [0, 1], seed=1)
    _conversation(a.stats, "conv-hid", P2, [0, 1], seed=2)
    b.pull(a)
    c.pull(b)
    assert _project_rows(c, a.iid, P2) > 0
    _conversation(a.stats, "conv-ok", P1, [1], seed=7)
    b.pull(a)
    real = mesh.post(c, b)

    async def faking(method: str, path: str, body: Optional[dict]) -> Tuple[int, Any]:
        status, page = await real(method, path, body)
        for group in page.get("groups", []):
            group["epoch"] += 5
        for entry in page["origins"].values():
            if "names_epoch" in entry:
                entry["names_epoch"] += 5
        return status, page

    before = _held(c, a.iid)
    c.importer._post_for = lambda iid: faking
    c.pull(b)
    assert _noted(c, "relay_forged") and _held(c, a.iid) == before and _project_rows(c, a.iid, P2) > 0, "nothing was dropped or stored on a claimed epoch"
    c.importer._post_for = lambda iid: real
    c.importer._noted.clear()
    _air_gap(monkeypatch, a, frozenset({P1}))
    _conversation(a.stats, "conv-new", P1, [3], seed=3)
    b.pull(a)
    assert _project_rows(b, a.iid, P2) == 0
    c.pull(b)
    assert _project_rows(c, a.iid, P2) == 0 and _project_rows(c, a.iid, P1) > 0 and not _noted(c, "relay_forged")


def test_one_bad_origin_does_not_block_the_others_and_names_clear_with_their_rows(world):
    mesh = world("a1", "a2", "b", "c")
    a1, a2, b, c = (mesh.nodes[n] for n in ("a1", "a2", "b", "c"))
    b.pair(a1, a2)
    c.pair(b)
    _conversation(a1.stats, "conv-1", P1, [0, 1], seed=1)
    _conversation(a2.stats, "conv-2", P1, [0, 1], seed=2)
    b.pull(a1)
    b.pull(a2)
    with closing(b.open_db()) as conn:
        conn.execute(f"UPDATE {USAGE_TABLE} SET input = input + 1 WHERE peer_install_id = ?", (a1.iid,))
        conn.commit()
    c.pull(b)
    assert _held(c, a1.iid) == (0, 0, 0) and _held(c, a2.iid)[0] > 0 and _noted(c, "relay_forged")
    with closing(b.open_db()) as conn:
        assert relay_store.names_proof(conn, a2.iid) is not None
        from src.core.pack.rollup_import.ddl import delete_origin_rows
        delete_origin_rows(conn, a2.iid)
        assert relay_store.names_proof(conn, a2.iid) is None, "a name list that is gone is never served as signed"


def test_one_unverifiable_origin_does_not_restamp_the_good_groups_every_beat(world):
    mesh = world("a1", "a2", "b", "c")
    a1, a2, b, c = (mesh.nodes[n] for n in ("a1", "a2", "b", "c"))
    b.pair(a1, a2)
    c.pair(b)
    _conversation(a1.stats, "conv-1", P1, [0, 1], seed=1)
    _conversation(a2.stats, "conv-2", P1, [0, 1], seed=2)
    b.pull(a1)
    b.pull(a2)
    with closing(b.open_db()) as conn:
        conn.execute(f"UPDATE {USAGE_TABLE} SET input = input + 1 WHERE peer_install_id = ?", (a1.iid,))
        conn.commit()
    c.pull(b)
    with closing(c.open_db()) as conn:
        held = relay_store.current_rev(conn)
    for _ in range(3):
        c.pull(b)
    with closing(c.open_db()) as conn:
        assert relay_store.current_rev(conn) == held
        assert conn.execute(f"SELECT COUNT(*) FROM {USAGE_TABLE} WHERE peer_install_id = ?", (a2.iid,)).fetchone()[0] > 0


def test_the_signed_own_build_and_epoch_are_one_critical_section():
    assert relay_export._SIGNED_OWN_LOCK.acquire(blocking=False) is True
    relay_export._SIGNED_OWN_LOCK.release()
