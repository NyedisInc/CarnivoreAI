from __future__ import annotations

import asyncio
import base64
import copy
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import federation_mesh_data_routes
from src.core.pack.machines import capabilities as caps
from src.core.pack.machines.roster_v2 import RosterComputerV2, RosterV2
from src.core.pack.machines.settings_sign import Signing
from src.core.pack.meshdata import envelope, gossip, hlc, status, wire
from src.core.pack.meshdata.store import FILENAME, RecordStore
from src.core.relay_identity.device_key import DeviceKey, b64url

CERT = base64.b64encode(b"x" * 40).decode()
NOW = 1_800_000_000_000


class World:

    def __init__(self, tmp: Path, *names: str) -> None:
        self.keys = {n: DeviceKey.from_seed(bytes([i + 3]) * 32) for i, n in enumerate(names)}
        self.listed = list(names)
        self.now = NOW
        self.signing = {n: self._signing(n) for n in names}
        self.stores = {n: RecordStore(tmp / f"{n}.db", f"iid-{n}", wall=lambda: self.now, signing=self.signing[n]) for n in names}

    def _signing(self, name: str) -> Signing:
        return Signing(install_id=f"iid-{name}", load_key=lambda: self.keys[name], pinned_key=lambda iid: None)

    def rotate(self, name: str) -> None:
        self.keys[name] = DeviceKey.from_seed(bytes([200 + len(name)]) * 32)
        self.signing[name] = self._signing(name)
        self.stores[name].signing = self.signing[name]

    def lst(self, without: tuple = ()) -> RosterV2:
        rows = [RosterComputerV2(install_id=f"iid-{n}", label=n, fed_public_key=b64url(self.keys[n].raw_pub), cert=CERT, mesh=True)
                for n in self.listed if n not in without]
        return RosterV2(generation=1, alpha=rows[0].install_id, home=rows[0].install_id, issued_at=1, computers=rows)

    def publish(self, name: str, label: str = "", version: str = "1.0") -> None:
        card = status.build(label or name, version, [], NOW - 1000)
        assert self.stores[name].put_own("status", f"iid-{name}", card, self.signing[name], force=True)

    def sync(self, src: str, dst: str, lst_src: Any = None, lst_dst: Any = None):
        lst_src, lst_dst = lst_src or self.lst(), lst_dst or self.lst()

        async def call(body: Dict[str, Any]) -> Dict[str, Any]:
            answer, _ = wire.handle_sync(self.stores[dst], json.loads(json.dumps(body)), f"iid-{src}", lst_dst, self.now)
            return json.loads(json.dumps(answer))
        return asyncio.run(wire.run_sync(self.stores[src], call, lst_src, f"iid-{dst}", lambda: self.now))

    def heard(self, name: str, lst: Any = None) -> Dict[str, Any]:
        return self.stores[name].heard(lst or self.lst(), self.now)

    def entry(self, name: str) -> Dict[str, Any]:
        return self.stores[name].servable(self.lst())[f"status:iid-{name}"]

    def forge(self, signer: str, origin: str, ms: int, ctr: int = 0, label: str = "x") -> Dict[str, Any]:
        value = status.build(label, "1.0", [], 1)
        stamp = [ms, ctr, f"iid-{origin}"]
        sig = envelope.sign(envelope.KIND_RECORD, f"status:iid-{origin}", stamp, envelope.body_hash(value), self.signing[signer])
        return {"v": value, "s": stamp, "sig": {"signer": f"iid-{signer}" if signer == origin else sig.signer, "sig": sig.sig}}


@pytest.fixture()
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(caps, "MESH_BUILD_ON", True)
    return lambda *names: World(tmp_path, *names)


def test_a_card_travels_through_a_forwarder_and_is_shown_as_passed(world):
    w = world("a", "b", "c")
    w.publish("a")
    w.sync("a", "b")
    assert w.heard("b")["iid-a"]["via"] == "direct"
    w.sync("b", "c")
    seen = w.heard("c")["iid-a"]
    assert seen["via"] == "passed" and seen["label"] == "a" and seen["age_s"] == 0 and "iid-c" not in w.heard("c")
    assert w.sync("b", "c")[0] == "no_change"
    store = w.stores["a"]
    assert not store.put_own("status", "iid-a", status.build("a", "1.0", [], NOW - 1000), w.signing["a"])


def test_forged_cards_are_refused_and_a_bad_origin_costs_only_itself(world):
    w = world("a", "b", "c")
    w.publish("a")
    w.publish("b")
    lst = w.lst()
    b_as_a = w.forge("b", "a", NOW)
    altered = copy.deepcopy(w.entry("a"))
    altered["v"]["label"] = "evil"
    out = w.stores["c"].offer_batch({"status:iid-a": altered, "status:iid-b": w.entry("b")}, "iid-b", lst, NOW)
    assert (out.accepted, out.refused, out.bad_origins) == (1, 1, {"iid-a"})
    assert set(w.heard("c")) == {"iid-b"}
    assert w.stores["c"].offer_batch({"status:iid-a": b_as_a}, "iid-b", lst, NOW).accepted == 0
    assert "iid-a" not in w.heard("c")


def test_an_older_card_is_never_taken_back_even_after_the_row_was_dropped(world):
    w = world("a", "b")
    w.publish("a", label="one")
    first = copy.deepcopy(w.entry("a"))
    w.now += 5000
    w.publish("a", label="two")
    w.sync("a", "b")
    lst = w.lst()
    assert w.stores["b"].offer_batch({"status:iid-a": first}, "iid-a", lst, w.now).stale == 1
    assert w.heard("b")["iid-a"]["label"] == "two"
    gone = w.lst(without=("a",))
    w.stores["b"].reconcile(gone)
    assert "iid-a" not in w.heard("b")
    assert w.stores["b"].offer_batch({"status:iid-a": first}, "iid-a", lst, w.now).stale == 1
    assert w.stores["b"].offer_batch({"status:iid-a": w.entry("a")}, "iid-a", lst, w.now).accepted == 1


def test_an_identical_card_is_not_rewritten(world, tmp_path):
    w = world("a", "b", "c")
    w.publish("a")
    w.sync("a", "b")
    before = w.heard("b")["iid-a"]
    watcher = sqlite3.connect(tmp_path / "b.db")
    marker = watcher.execute("PRAGMA data_version").fetchone()[0]
    w.now += 60_000
    out = w.stores["b"].offer_batch({"status:iid-a": w.entry("a")}, "iid-c", w.lst(), w.now)
    assert (out.same, out.accepted) == (1, 0)
    assert watcher.execute("PRAGMA data_version").fetchone()[0] == marker
    assert w.heard("b")["iid-a"]["received_ms"] == before["received_ms"]
    watcher.close()


def test_a_removed_computers_card_is_refused_and_not_shown(world):
    w = world("a", "b", "c")
    w.publish("a")
    w.sync("a", "b")
    gone = w.lst(without=("a",))
    assert "iid-a" not in w.heard("b", gone)
    assert w.stores["b"].offer_batch({"status:iid-a": w.entry("a")}, "iid-a", gone, w.now).accepted == 0
    assert w.stores["c"].offer_batch({"status:iid-a": w.entry("a")}, "iid-b", gone, w.now).accepted == 0


def test_a_key_rotation_resigns_at_the_same_stamp_and_old_key_copies_die(world):
    w = world("a", "b", "c")
    w.publish("a")
    w.sync("a", "b")
    w.sync("a", "c")
    old = copy.deepcopy(w.entry("a"))
    w.rotate("a")
    new_list = w.lst()
    assert "iid-a" not in w.heard("b", new_list)
    w.stores["b"].reconcile(new_list)
    w.stores["a"].reconcile(new_list)
    resigned = w.entry("a")
    assert resigned["s"] == old["s"] and resigned["v"] == old["v"] and resigned["sig"] != old["sig"]
    assert w.stores["b"].offer_batch({"status:iid-a": old}, "iid-c", new_list, w.now).accepted == 0
    assert w.stores["b"].offer_batch({"status:iid-a": resigned}, "iid-a", new_list, w.now).accepted == 1
    assert w.heard("b", new_list)["iid-a"]["via"] == "direct"


def test_clock_limits_and_absurd_numbers(world):
    w = world("a", "b")
    lst = w.lst()
    store = w.stores["b"]
    assert store.offer_batch({"status:iid-a": w.forge("a", "a", NOW + 301_000)}, "iid-a", lst, NOW).accepted == 0
    assert store.offer_batch({"status:iid-a": w.forge("a", "a", NOW + 299_000)}, "iid-a", lst, NOW).accepted == 1
    for ms, ctr in ((2 ** 63, 0), (2 ** 53, 0), (5, 70000), (5, -1), (True, 0)):
        entry = w.forge("a", "a", NOW)
        entry["s"] = [ms, ctr, "iid-a"]
        assert store.offer_batch({"status:iid-a": entry}, "iid-a", lst, NOW).accepted == 0
    assert hlc.parse_stamp([2 ** 63, 0, "a"]) is None and hlc.parse_stamp([1, 70000, "a"]) is None
    clock = hlc.Clock("iid-b", None, wall=lambda: NOW)
    clock.see(hlc.Stamp(NOW + 10 ** 12, 0, "x"))
    assert clock.last.ms == NOW + hlc.FOLD_LEAD_MS
    clock.see(hlc.Stamp(hlc.MAX_MS, hlc.MAX_CTR, "x"))
    assert clock.last.ms == NOW + hlc.FOLD_LEAD_MS
    assert clock.now() > hlc.Stamp(NOW + hlc.FOLD_LEAD_MS, 0, "")


def test_a_flood_leaves_at_most_64_rows_and_a_huge_request_is_refused(world):
    w = world("a", "b")
    lst, store = w.lst(), w.stores["b"]
    junk_sig = {"signer": "iid-a", "sig": b64url(b"x" * 64)}
    big = {"label": "x" * 5000, "app_version": "1", "links": [], "up_since": 1}
    entries: List[tuple] = []
    for i in range(13000):
        kind = i % 4
        if kind == 0:
            entries.append((f"nokind{i}:iid-a", {"v": {}, "s": [NOW, 0, "iid-a"], "sig": junk_sig}))
        elif kind == 1:
            entries.append((f"status:other-{i}", {"v": status.build("x", "1", [], 1), "s": [NOW, 0, "iid-a"], "sig": junk_sig}))
        elif kind == 2:
            entries.append(("status:iid-a", {"v": big, "s": [NOW, 0, "iid-a"], "sig": junk_sig}))
        else:
            entries.append(("status:iid-a", {"v": status.build("x", "1", [], 1), "s": [NOW, 0, "iid-a"], "sig": junk_sig}))
    for start in range(0, len(entries), 512):
        out = store.offer_batch(dict(entries[start:start + 512]), "iid-a", lst, NOW)
        assert out.accepted == 0
    assert store.servable(lst) == {}
    body = {"v": 1, "digest": "d", "buckets": 1, "bucket": 0, "records": {f"status:k{i}": {} for i in range(513)}}
    with pytest.raises(ValueError):
        wire.handle_sync(store, body, "iid-a", lst, NOW)


def test_with_the_switch_off_the_route_is_a_plain_404_and_no_file_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(caps, "MESH_BUILD_ON", False)
    app = FastAPI()
    app.include_router(federation_mesh_data_routes.router, prefix="/api/v1")
    client = TestClient(app)
    probe = client.post("/api/v1/federation/pack/mesh/sync", json={})
    unknown = client.post("/api/v1/federation/pack/mesh/nothing", json={})
    assert (probe.status_code, probe.json()) == (404, {"detail": "Not Found"}) and probe.content == unknown.content
    signing = Signing(install_id="iid-a", load_key=lambda: DeviceKey.from_seed(b"\x01" * 32), pinned_key=lambda iid: None)
    asyncio.run(gossip.start(state_dir=lambda: str(tmp_path), links_getter=lambda: None, signing=signing, held_list=lambda: None,
                             label=lambda: "a", app_version="1", own_iid="iid-a"))
    assert not (tmp_path / FILENAME).exists() and gossip.ACTIVE is None
