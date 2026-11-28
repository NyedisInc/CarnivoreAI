from __future__ import annotations

import asyncio
import base64
import copy
import json
import secrets
import time
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set, Tuple

import pytest
from structlog.testing import capture_logs

from src.core import relay_keychain
from src.core.computers import direction
from src.core.notifications import doc_model, types
from src.core.notifications.destinations.secrets import DestinationSecrets
from src.core.notifications.destinations.service import NotificationService
from src.core.notifications.settings_doc import routes, styles_store, ticks  # noqa: F401
from src.core.notifications.sync import mesh_notify, runtime, status, wire as nwire
from src.core.pack.machines import capabilities as caps
from src.core.pack.machines.roster_v2 import RosterComputerV2, RosterV2
from src.core.pack.machines.settings_sign import Signing
from src.core.pack.meshdata import envelope, gossip, hlc, kinds, notify_kind, wire
from src.core.pack.meshdata.store import RecordStore
from src.core.relay_identity.device_key import DeviceKey, b64url

CERT = base64.b64encode(b"x" * 40).decode()
TYPES = [t.id for t in types.ordered_types()]


class FakeKeychain:

    def __init__(self) -> None:
        self.items: Dict[Tuple[str, str], str] = {}

    def read_state(self, service: str, account: str) -> Any:
        v = self.items.get((service, account))
        return (relay_keychain.READ_OK, v) if v else (relay_keychain.READ_ABSENT, None)

    def write(self, service: str, account: str, secret: str) -> None:
        self.items[(service, account)] = secret

    def delete(self, service: str, account: str) -> bool:
        return self.items.pop((service, account), None) is not None


class Reply:

    def __init__(self, body: Dict[str, Any]) -> None:
        self.status_code, self._body = 200, body

    def json(self) -> Dict[str, Any]:
        return self._body


class Client:

    def __init__(self, world: "World", src: str, dst: str) -> None:
        self.world, self.src, self.dst = world, src, dst

    async def request(self, method: str, path: str, json: Optional[dict] = None, **_kw: Any) -> Reply:
        assert (method, path) == ("POST", gossip.SYNC_PATH), (method, path)
        answer, _ = wire.handle_sync(self.world.stores[self.dst], copy.deepcopy(json), f"iid-{self.src}", self.world.lst(), hlc.wall_ms())
        return Reply(answer)


class Registry:

    def __init__(self, links: List[Tuple[str, Any]]) -> None:
        self._links = links

    def connected(self) -> List[Tuple[str, Any]]:
        return list(self._links)

    def capabilities(self, iid: str) -> List[str]:
        return [caps.CAP_MESH]


class MeshApi:

    def __init__(self, lst: Any) -> None:
        self._lst = lst

    def trusted(self, iid: str) -> Any:
        return self._lst

    def on_demand(self, iid: str) -> bool:
        return False


class World:

    def __init__(self, tmp: Path, names: List[str], alpha: str = "z") -> None:
        self.tmp, self.names, self.alpha = tmp, list(names), alpha
        every = ["z"] + [n for n in self.names if n != "z"]
        self.keys = {n: DeviceKey.from_seed(bytes([i + 3]) * 32) for i, n in enumerate(every)}
        self.signing = {n: Signing(install_id=f"iid-{n}", load_key=lambda n=n: self.keys[n], pinned_key=lambda iid: None) for n in self.keys}
        self.stores = {n: RecordStore(tmp / f"{n}.db", f"iid-{n}", signing=self.signing[n]) for n in self.names}
        self.removed: Set[str] = set()
        self.clients: Dict[Tuple[str, str], Client] = {}
        self.services: Dict[str, gossip.Gossip] = {}
        self.ns: Dict[str, NotificationService] = {}
        self.keychains: Dict[str, FakeKeychain] = {}
        self.steps: Dict[str, Any] = {}
        self.prepares: Dict[str, Any] = {}
        for n in self.names:
            self.ns[n] = self.notification_service(n)
            gossip.STEPS[:] = []
            gossip.PREPARE[:] = []
            mesh_notify.attach(self.ns[n].docs)
            self.steps[n] = gossip.STEPS.pop()
            self.prepares[n] = gossip.PREPARE.pop()
        self.link([])

    def notification_service(self, name: str) -> NotificationService:
        path = self.tmp / f"{name}.json"
        path.write_text(json.dumps({"agents": {}}))
        service = NotificationService(path)
        self.keychains[name] = FakeKeychain()
        service.secrets = DestinationSecrets(backend=self.keychains[name])
        service.destinations._secrets = service.secrets
        return service

    def lst(self) -> RosterV2:
        rows = [RosterComputerV2(install_id=f"iid-{n}", label=n, fed_public_key=b64url(self.keys[n].raw_pub), cert=CERT, mesh=True, may_receive_logins=True)
                for n in self.keys if n not in self.removed]
        return RosterV2(generation=1, alpha=f"iid-{self.alpha}", home=f"iid-{self.alpha}", issued_at=1, computers=rows)

    def link(self, pairs: List[Tuple[str, str]]) -> None:
        for a, b in pairs:
            self.clients[(a, b)], self.clients[(b, a)] = Client(self, a, b), Client(self, b, a)
        for n in self.names:
            star = [(f"iid-{d}", c) for (src, d), c in self.clients.items() if src == n and self.alpha in (n, d)]
            reg = Registry([(f"iid-{d}", c) for (src, d), c in self.clients.items() if src == n and self.alpha not in (n, d)])
            links = SimpleNamespace(connected_clients=lambda star=star: list(star), capabilities=lambda iid: [caps.CAP_MESH])
            self.services[n] = gossip.Gossip(
                self.stores[n], links_getter=lambda links=links: links, signing=self.signing[n], held_list=self.lst, label=lambda n=n: n, app_version="1.0",
                own_iid=f"iid-{n}", members=lambda lst, n=n, reg=reg: gossip.member_links(lst, f"iid-{n}", reg, MeshApi(lst)))

    def tick(self, name: str) -> None:
        gossip.STEPS[:] = [self.steps[name]]
        gossip.PREPARE[:] = [self.prepares[name]]
        asyncio.run(self.services[name].pass_once())

    def doc(self, name: str) -> Dict[str, Any]:
        return self.ns[name].docs.snapshot()

    def set(self, name: str, path: str, value: Any) -> Dict[str, Any]:
        doc = self.ns[name].docs.update(lambda d, me: doc_model.set_global(d, path, value, me))
        return doc["global"][path]

    def entry(self, signer: str, key: str, value: Any, ms: int, ctr: int = 0) -> Dict[str, Any]:
        stamp = [ms, ctr, f"iid-{signer}"]
        sig = envelope.sign(envelope.KIND_RECORD, f"notify:{key}", stamp, envelope.body_hash(value), self.signing[signer])
        return {"v": value, "s": stamp, "sig": sig.to_dict()}

    def offer(self, dst: str, entries: Dict[str, Any], via: str) -> Any:
        return self.stores[dst].offer_batch(entries, f"iid-{via}", self.lst(), hlc.wall_ms())

    def keys_held(self, name: str) -> Dict[str, Any]:
        return {k: s for k, (_v, s) in self.stores[name].kind_rows(self.lst(), "notify").items()}


@pytest.fixture()
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(caps, "MESH_BUILD_ON", True)
    monkeypatch.setattr(direction, "contained", lambda iid: False)
    monkeypatch.setattr(direction, "one_way_ids", lambda: [])
    monkeypatch.setattr(direction, "is_one_way_toward", lambda iid: False)
    monkeypatch.setattr(gossip, "STEPS", [])
    monkeypatch.setattr(gossip, "PREPARE", [])
    monkeypatch.setattr(notify_kind, "_FRESH", set())
    monkeypatch.setattr(notify_kind, "_GATES", {})
    from src.core.notifications.settings_doc import store as store_mod
    monkeypatch.setattr(store_mod.resource_push, "notify", lambda *a, **k: None)
    return lambda names, **kw: World(tmp_path, names, **kw)


def test_a_change_on_a_reaches_c_through_b_with_no_alpha_and_no_legacy_exchange(world, monkeypatch):
    async def never(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("the legacy notify exchange was used")

    monkeypatch.setattr(nwire, "run_exchange", never)
    monkeypatch.setattr(nwire, "serve_exchange", never)
    w = world(["a", "b", "c"])
    w.link([("a", "b"), ("b", "c")])
    path = doc_model.mute_path(TYPES[0])
    written = w.set("a", path, True)
    for n in ("a", "b", "c", "b", "c"):
        w.tick(n)
    assert w.doc("c")["global"][path] == written == w.doc("b")["global"][path]
    assert w.keys_held("c")[path].iid == "iid-a"
    assert ("z", "a") not in w.clients and not any("iid-z" in (c.src, c.dst) for c in w.clients.values())


def test_a_secret_or_a_destination_never_rides_a_record_and_real_writers_pass(world, caplog):
    w = world(["a", "b", "c"])
    w.link([("a", "b"), ("b", "c")])
    canary = secrets.token_hex(16)
    dest = asyncio.run(w.ns["a"].destinations.create("slack", "team", {}, {"url": f"https://hooks.slack.com/services/T0/B0/{canary}"})).destination["id"]
    assert w.keychains["a"].items
    docs = w.ns["a"].docs
    ticks.put_tick(docs, "screen", TYPES[0], False)
    ticks.put_default(docs, TYPES[1], False)
    styles_store.put_style(docs, TYPES[0], "ask", "active")
    routes.put_master(docs, [TYPES[2]], False)
    w.set("a", doc_model.mute_path(TYPES[3]), True)
    from src.core.notifications.destinations import extras
    extras.set_extras(docs, dest, {"away": True, "projects": ["one"], "reminder_minutes": 5})
    seen_kinds: Set[str] = set()
    for path, entry in docs.snapshot()["global"].items():
        kind = path.partition("/")[0]
        if kind == "dest":
            assert not notify_kind.valid(path, entry)
        else:
            seen_kinds.add(kind)
            assert notify_kind.valid(path, entry), path
    assert {"tick", "extra", "default", "mute", "style", "on"} <= seen_kinds
    with capture_logs() as logs:
        for n in ("a", "b", "c", "b", "c"):
            w.tick(n)
    held = w.keys_held("a")
    assert held and not [k for k in held if k.startswith(("dest/", "local/")) or "desktop" in k]
    blobs = [json.dumps(w.stores["a"].view(w.lst())[0]), json.dumps(logs, default=str), caplog.text]
    for name in ("a", "b", "c"):
        blobs += [p.read_bytes().decode("latin-1") for p in w.tmp.glob(f"{name}.db*")]
    assert all(canary not in blob for blob in blobs)
    assert f"dest/{dest}" not in w.doc("c")["global"] and not [k for k in w.keys_held("c") if k.startswith("dest/")]


def test_route_cells_pass(world):
    w = world(["a"])
    path = doc_model.route_path("iid-a", "phone", TYPES[0])
    entry = w.set("a", path, True)
    assert notify_kind.valid(path, entry)


def test_every_hostile_shape_is_refused_by_a_listed_origin_and_none_is_held(world):
    w = world(["a", "b", "c"])
    now = hlc.wall_ms() - 1000
    good = {"val": True, "ver": [1, "n_x"]}
    dest_id = "d_0123456789ab"
    record = {"kind": "slack", "name": "t", "enabled": True, "config": {}, "secret_fields": ["url"], "secret_rev": 3}
    d2, d3 = "d_0123456789ac", "d_0123456789ad"
    rows = [
        (f"dest/{dest_id}", {"val": record, "ver": [1, "n_x"]}),
        (f"dest/{d2}", {"val": {**record, "config": {"url": "https://example.test/x"}}, "ver": [1, "n_x"]}),
        (f"extra/{dest_id}/projects", {"val": ["a", {"k": 1}], "ver": [1, "n_x"]}),
        (f"mute/{TYPES[0]}", {**good, "extra": 1}),
        (f"extra/{d2}/projects", {"val": ["p" * 120] * 60, "ver": [1, "n_x"]}),
        ("local/x", good),
        (f"tick/desktop/{TYPES[0]}", good),
        (f"tick/webpush:s1/{TYPES[0]}", good),
        (f"mute/{TYPES[1]}", {"val": 1, "ver": [1, "n_x"]}),
        (f"mute/{TYPES[2]}", {"val": True, "ver": [2 ** 53, "n_x"]}),
        (f"extra/{d3}/away", {"val": True, "ver": [1, "n_x"], "tomb": 5}),
    ]
    offered = {f"notify:{key}": w.entry("a", key, value, now) for key, value in rows}
    w.tick("c")
    out = w.offer("c", offered, "b")
    assert out.accepted == 0 and out.refused == len(offered), out
    assert not w.keys_held("c")
    for key, value in rows:
        assert not notify_kind.valid(key, value)
    control = {f"notify:mute/{TYPES[3]}": w.entry("a", f"mute/{TYPES[3]}", good, now)}
    assert w.offer("c", control, "b").accepted == 1


def test_a_forged_origin_and_an_older_signed_copy_are_refused_and_the_document_is_unchanged(world):
    w = world(["a", "b", "c"])
    now = hlc.wall_ms()
    path = f"mute/{TYPES[0]}"
    new = {"val": True, "ver": [4, "n_a"]}
    old = {"val": False, "ver": [2, "n_a"]}
    w.tick("c")
    forged = w.entry("b", path, {"val": True, "ver": [9, "n_b"]}, now - 500)
    forged["s"][2] = "iid-a"
    assert w.offer("c", {f"notify:{path}": forged}, "b").accepted == 0
    assert w.offer("c", {f"notify:{path}": w.entry("a", path, new, now - 1000)}, "b").accepted == 1
    w.tick("c")
    rev = w.doc("c")["rev"]
    assert w.doc("c")["global"][path] == new
    assert w.offer("c", {f"notify:{path}": w.entry("a", path, old, now - 5000)}, "b").stale == 1
    assert w.offer("c", {f"notify:{path}": w.entry("a", path, old, now - 100)}, "b").accepted == 1
    w.tick("c")
    assert w.doc("c")["global"][path] == new and w.doc("c")["rev"] == rev


def test_the_legacy_exchange_and_the_records_do_not_double_apply_or_ping_pong(world):
    w = world(["a", "b"], alpha="a")
    w.link([("a", "b")])
    o = w.notification_service("o")
    gateway_calls: List[str] = []

    def legacy(caller: Any, callee: Any) -> Any:
        async def call(body: Dict[str, Any]) -> Dict[str, Any]:
            gateway_calls.append("x")
            return await nwire.serve_exchange(callee.docs, callee.secrets, body, time.time())
        return asyncio.run(nwire.run_exchange(caller.docs, call, time.time))

    w.set("a", doc_model.mute_path(TYPES[5]), True)
    for _ in range(3):
        legacy(w.ns["a"], o)
        for n in ("a", "b", "a", "b"):
            w.tick(n)
    before = w.keys_held("a")
    rev_a = w.doc("a")["rev"]
    edit = o.docs.update(lambda d, me: doc_model.set_global(d, doc_model.mute_path(TYPES[0]), True, me))["global"][doc_model.mute_path(TYPES[0])]
    legacy(w.ns["a"], o)
    w.tick("a")
    after = w.keys_held("a")
    assert [k for k in after if after[k] != before.get(k)] == [doc_model.mute_path(TYPES[0])]
    w.tick("b")
    assert w.doc("b")["global"][doc_model.mute_path(TYPES[0])] == edit
    e2 = w.set("b", doc_model.mute_path(TYPES[1]), True)
    for n in ("b", "a"):
        w.tick(n)
    assert w.doc("a")["global"][doc_model.mute_path(TYPES[1])] == e2
    legacy(w.ns["a"], o)
    assert o.docs.snapshot()["global"][doc_model.mute_path(TYPES[1])] == e2
    settled = (w.keys_held("a"), w.keys_held("b"), w.doc("a")["rev"], w.doc("b")["rev"], o.docs.snapshot()["rev"])
    for n in ("a", "b", "a", "b"):
        w.tick(n)
    assert legacy(w.ns["a"], o).result == nwire.RESULT_NO_CHANGE
    assert (w.keys_held("a"), w.keys_held("b"), w.doc("a")["rev"], w.doc("b")["rev"], o.docs.snapshot()["rev"]) == settled
    assert w.doc("a")["rev"] == rev_a + 2


def test_a_computer_that_switched_its_alpha_off_takes_no_part_and_a_peer_switched_off_is_not_applied(world):
    w = world(["a", "b", "c"])
    w.link([("a", "b"), ("b", "c")])
    p0, p1 = doc_model.mute_path(TYPES[0]), doc_model.mute_path(TYPES[1])
    e0 = w.set("a", p0, True)
    for n in ("a", "b", "c", "b", "c"):
        w.tick(n)
    assert w.doc("c")["global"][p0] == e0
    w.ns["b"].docs.update(lambda d, me: status.with_enabled(d, "iid-z", False))
    own_edit = w.set("b", p1, True)
    held_before, doc_before = w.keys_held("b"), w.doc("b")["global"]
    w.tick("b")
    assert held_before and w.keys_held("b") == {}
    assert w.doc("b")["global"] == doc_before and w.doc("b")["global"][p1] == own_edit
    late = {f"notify:{doc_model.mute_path(TYPES[2])}": w.entry("a", doc_model.mute_path(TYPES[2]), {"val": True, "ver": [1, "n_a"]}, hlc.wall_ms() - 100)}
    assert w.offer("b", late, "a").accepted == 0
    w.ns["b"].docs.update(lambda d, me: status.with_enabled(d, "iid-z", True))
    w.ns["a"].docs.update(lambda d, me: status.with_enabled(d, "iid-b", False))
    w.tick("b")
    w.tick("a")
    assert p1 not in w.doc("a")["global"]
    w.ns["a"].docs.update(lambda d, me: status.with_enabled(d, "iid-b", True))
    w.tick("a")
    assert w.doc("a")["global"][p1] == own_edit


def test_a_value_that_lost_to_a_concurrent_record_while_its_author_left_still_converges(world):
    w = world(["x", "y", "b", "c"])
    w.link([("b", "c")])
    path = doc_model.mute_path(TYPES[0])
    now = hlc.wall_ms()
    w.tick("b")
    x_entry = {"val": True, "ver": [5, "n_x"]}
    y_entry = {"val": False, "ver": [3, "n_y"]}
    assert w.offer("b", {f"notify:{path}": w.entry("x", path, x_entry, now - 3000)}, "x").accepted == 1
    w.tick("b")
    assert w.doc("b")["global"][path] == x_entry
    assert w.offer("b", {f"notify:{path}": w.entry("y", path, y_entry, now - 1000)}, "y").accepted == 1
    w.tick("b")
    assert w.keys_held("b")[path].iid == "iid-y" and w.doc("b")["global"][path] == x_entry
    w.removed.add("x")
    w.tick("b")
    assert w.keys_held("b")[path].iid == "iid-b"
    w.tick("c")
    w.tick("c")
    assert w.doc("c")["global"][path] == x_entry


def test_with_the_switch_off_the_runtime_registers_no_step_and_no_listener(tmp_path, monkeypatch):
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"agents": {}}))
    service = NotificationService(path)
    monkeypatch.setattr(runtime, "get_service", lambda state: service)
    monkeypatch.setattr(gossip, "STEPS", [])
    monkeypatch.setattr(gossip, "PREPARE", [])
    from src.core.federation import peer_links
    monkeypatch.setattr(peer_links, "LINKS", None)

    async def boot() -> Tuple[int, int]:
        task = runtime.start(SimpleNamespace(), lambda: None)
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return len(service.docs._listeners), len(gossip.STEPS) + len(gossip.PREPARE)

    monkeypatch.setattr(caps, "MESH_BUILD_ON", False)
    off = asyncio.run(boot())
    assert off[1] == 0
    service.docs._listeners.clear()
    monkeypatch.setattr(caps, "MESH_BUILD_ON", True)
    on = asyncio.run(boot())
    assert on[1] == 2 and on[0] == off[0] + 1


def test_the_kind_is_known_and_has_no_destination_in_its_allow_list():
    assert "notify" in kinds.KINDS and kinds.KINDS["notify"].tomb_value is None
    assert doc_model.KIND_DEST not in notify_kind.ALLOWED and doc_model.KIND_LOCAL not in notify_kind.ALLOWED
    assert kinds.KINDS["notify"].cap <= 4000


def _restart(w: "World", name: str) -> None:
    w.stores[name] = RecordStore(w.tmp / f"{name}.db", f"iid-{name}", signing=w.signing[name])
    w.link([])
    notify_kind._GATES.pop(f"iid-{name}", None)
    notify_kind._FRESH.discard(f"iid-{name}")


def _six_mutes(w: "World") -> Dict[str, Any]:
    w.link([("a", "b")])
    for t in TYPES[:6]:
        w.set("a", doc_model.mute_path(t), True)
    for n in ("a", "b", "a", "b"):
        w.tick(n)
    held = w.keys_held("a")
    assert len(held) >= 6 and w.keys_held("b").keys() == held.keys()
    return held


def test_alpha_restart_resigns_nothing(world):
    w = world(["a", "b"], alpha="a")
    before = _six_mutes(w)
    _restart(w, "a")
    w.tick("a")
    after = w.keys_held("a")
    assert after.keys() == before.keys() and [k for k in after if after[k] != before[k]] == []


def test_member_restart_keeps_rows(world):
    w = world(["a", "b"], alpha="a")
    before = _six_mutes(w)
    _restart(w, "b")
    w.tick("b")
    assert w.keys_held("b") == w.keys_held("a") == before


def test_switched_off_holds_and_serves_nothing(world):
    w = world(["a", "b", "c"], alpha="a")
    _six_mutes(w)
    assert notify_kind.START[0] is True
    assert w.keys_held("b")
    notify_kind.set_gate("iid-b", False, {"iid-a"})
    lst0 = w.lst()
    assert [k for k in w.stores["b"].view(lst0, "iid-a")[0] if k.startswith("notify:")] == []
    assert [k for k in w.stores["b"].view(lst0, "iid-c")[0] if k.startswith("notify:")] != []
    w.ns["b"].docs.update(lambda d, me: status.with_enabled(d, "iid-a", False))
    w.tick("b")
    assert w.keys_held("b") == {}
    assert notify_kind.gate("iid-b")[0] is True and notify_kind.gate("iid-a")[0] is False
    store_a, store_b, lst = w.stores["a"], w.stores["b"], w.lst()
    assert [k for k, v in store_b.view(lst, "iid-a")[0].items() if k.startswith("notify:")] == []
    asyncio.run(w.services["b"]._one("iid-a", w.clients[("b", "a")], lst, asyncio.Semaphore(1), store_b.generation))
    assert w.keys_held("b") == {}


def test_prune_memo_sees_gate(world):
    w = world(["a", "b"], alpha="a")
    _six_mutes(w)
    store_b, lst = w.stores["b"], w.lst()
    assert w.keys_held("b") and store_b.prune(lst) == 0
    notify_kind.set_gate("iid-b", True, frozenset())
    assert store_b.prune(lst) >= 6 and w.keys_held("b") == {}


def _break_hook(w: "World", name: str, monkeypatch) -> None:
    def boom():
        raise RuntimeError("transient")
    monkeypatch.setattr(w.ns[name].docs, "snapshot", boom)


def test_failed_hook_keeps_rows_and_serves_nothing(world, monkeypatch):
    w = world(["a", "b"], alpha="a")
    before = _six_mutes(w)
    good = w.ns["b"].docs.snapshot
    _break_hook(w, "b", monkeypatch)
    w.tick("b")
    assert w.keys_held("b") == before
    lst = w.lst()
    assert [k for k in w.stores["b"].view(lst, "iid-a")[0] if k.startswith("notify:")] == []
    w.set("a", doc_model.mute_path(TYPES[6]), True)
    w.tick("a")
    fresh = {k: v for k, v in w.keys_held("a").items() if k not in before}
    assert fresh
    for k in fresh:
        value = w.stores["a"].kind_rows(lst, "notify")[k][0]
        w.offer("b", {f"notify:{k}": w.entry("a", k, value, hlc.wall_ms() + 1)}, "a")
    assert w.keys_held("b") == before
    monkeypatch.setattr(w.ns["b"].docs, "snapshot", good)
    w.tick("b")
    w.tick("b")
    after = w.keys_held("b")
    assert all(after[k] == before[k] for k in before)
    assert [k for k in w.stores["b"].view(lst, "iid-a")[0] if k.startswith("notify:")] != []
    _restart(w, "b")
    _break_hook(w, "b", monkeypatch)
    w.tick("b")
    assert all(w.keys_held("b").get(k) == v for k, v in before.items())
