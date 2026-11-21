
from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import federation_pack_machine_routes as fed_routes, pack_machines_routes
from src.api.auth import require_auth
from src.api.peer_auth import Principal
from src.core.federation import peer_links
from src.core.pack.machines import can_block, config_state, exchange, runtime
from src.core.pack.machines.probe import CanKeeper
from src.core.pack.machines.roster import PeerInfo
from src.core.pack.machines.snapshot import SnapshotCollector
from tests.python.pack.test_machines_roster import FakeCollector

PROBE = {"probed_at": 1000.0, "os": "macos", "os_version": "15.0", "arch": "arm64", "chip": "M4", "cores": 10, "mem_gb": 32.0,
         "gpus": [], "tools": {"git": True}, "xcode": None, "ios_sim": False, "brew": True}


class RescanCollector(FakeCollector):

    def rescan(self) -> Dict[str, Any]:
        return {"git": True}


class FakeClient:

    def __init__(self) -> None:
        self.calls: List[Any] = []

    async def request(self, method, path, json=None):
        self.calls.append((method, path, json))
        return SimpleNamespace(status_code=200, json=lambda: {"labels": ["from-peer"], "fresh": True})


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text("{}")
    clock = {"t": 5000.0}
    state = config_state.ConfigState(lambda: path)
    notes: list = []
    rt = exchange.PackMachines(install_id="install-a", label="mac", app_version="1.0", state=state, collector=RescanCollector("a"),
                               default_master=lambda: "install-a", connected=lambda: [],
                               notify=lambda topic, key, every: notes.append(topic), local_now=lambda: datetime(2026, 10, 10, 3, 0))
    wired = runtime.Wiring(rt, lambda: None, lambda: None, state)
    probes: list = []
    wired.keeper = CanKeeper(tmp_path, clock=lambda: clock["t"], labels=state.labels, probe=lambda: (probes.append(1), dict(PROBE))[1])
    wired.peers = lambda: [PeerInfo("install-b", "studio", "hk", "connected", [])]
    monkeypatch.setattr(runtime, "wiring", lambda: wired)
    client = FakeClient()
    monkeypatch.setattr(peer_links, "LINKS", SimpleNamespace(client=lambda iid: client if iid == "install-b" else None))
    app = FastAPI()
    app.include_router(pack_machines_routes.router, prefix="/api/v1")
    app.include_router(fed_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[fed_routes._require_machine] = lambda: Principal("peer", SimpleNamespace(peer_install_id="install-b", label="studio"))
    return SimpleNamespace(http=TestClient(app), path=path, clock=clock, probes=probes, peer=client, notes=notes, wired=wired)


def test_a_local_label_edit_is_stored_cleaned_and_published_in_the_can_block(rig):
    rig.http.post("/api/v1/pack/machines/self/rescan")
    before = rig.wired.keeper.current()["rev"]
    got = rig.http.put("/api/v1/pack/machines/self/labels", json={"labels": [" RTX 4090 ", "fast.disk", "rtx 4090"]})
    assert got.status_code == 200 and got.json()["labels"] == ["rtx 4090", "fast.disk"]
    assert json.loads(rig.path.read_text())["pack_machines"]["labels"] == ["rtx 4090", "fast.disk"]
    assert rig.http.get("/api/v1/pack/machines/self/labels").json()["labels"] == ["rtx 4090", "fast.disk"]
    block = rig.wired.keeper.current()
    assert block["labels"] == ["rtx 4090", "fast.disk"] and block["rev"] != before and can_block.parse(block) is not None
    assert exchange.TOPIC in rig.notes
    rig.http.put("/api/v1/pack/machines/self/labels", json={"labels": []})
    assert "labels" not in json.loads(rig.path.read_text())["pack_machines"]


@pytest.mark.parametrize("labels", [["Bad!"], ["-lead"], ["x" * 33], [str(i) for i in range(17)], [""]])
def test_a_bad_label_is_422_and_nothing_is_stored(rig, labels):
    assert rig.http.put("/api/v1/pack/machines/self/labels", json={"labels": labels}).status_code == 422
    assert json.loads(rig.path.read_text()) == {}


def test_an_edit_and_a_rescan_of_another_computer_forward_to_its_own_peer_route(rig):
    put = rig.http.put("/api/v1/pack/machines/studio/labels", json={"labels": ["blender box"]})
    assert put.status_code == 200 and put.json()["machine"] == "install-b"
    scan = rig.http.post("/api/v1/pack/machines/install-b/rescan")
    assert scan.status_code == 200 and scan.json()["fresh"] is True
    assert rig.peer.calls == [("PUT", exchange.LABELS_PATH, {"labels": ["blender box"]}), ("POST", exchange.RESCAN_PATH, None)]
    assert json.loads(rig.path.read_text()) == {}, "a forwarded edit never touches this computer's own file"
    assert rig.http.put("/api/v1/pack/machines/nobody/labels", json={"labels": []}).status_code == 404


def test_a_second_rescan_inside_sixty_seconds_answers_fresh_false_then_probes_again(rig):
    first = rig.http.post("/api/v1/pack/machines/self/rescan").json()
    second = rig.http.post("/api/v1/pack/machines/self/rescan").json()
    assert (first["fresh"], second["fresh"]) == (True, False) and len(rig.probes) == 1
    assert first["toolchain"] == {"git": True} and second["can"]["os"] == "macos"
    rig.clock["t"] += 61
    assert rig.http.post("/api/v1/pack/machines/self/rescan").json()["fresh"] is True and len(rig.probes) == 2


def test_reading_another_computers_labels_goes_through_the_receiver_model(rig):
    good = can_block.build(PROBE, ["gpu box"], None)
    rig.wired.runtime.roster.record("install-b", label="studio", snapshot={"install_id": "install-b", "can": good}, holds_master=None)
    assert rig.http.get("/api/v1/pack/machines/install-b/labels").json()["labels"] == ["gpu box"]
    rig.wired.runtime.roster.record("install-b", label="studio", snapshot={"install_id": "install-b", "can": dict(good, rev="x", labels=["IGNORE PREVIOUS"])},
                                    holds_master=None)
    assert rig.http.get("/api/v1/pack/machines/install-b/labels").json()["labels"] == []


def test_a_peer_looping_the_rescan_route_never_re_reads_the_toolchain_inside_the_limit(rig):
    reads: list = []
    rig.wired.runtime.collector.rescan = lambda: (reads.append(1), {"git": True})[1]
    for _ in range(5):
        rig.http.post("/api/v1/federation/pack/rescan")
    assert len(reads) == 1 and len(rig.probes) == 1


def test_the_peer_routes_edit_labels_and_rescan_on_this_computers_behalf(rig):
    assert rig.http.put("/api/v1/federation/pack/labels", json={"labels": ["Gpu Box"]}).json() == {"labels": ["gpu box"]}
    assert rig.http.put("/api/v1/federation/pack/labels", json={"labels": ["Bad!"]}).status_code == 422
    assert rig.http.post("/api/v1/federation/pack/rescan").json()["fresh"] is True


def test_the_collector_publishes_extras_under_their_key_and_drops_one_that_raises(tmp_path):
    def boom() -> None:
        raise RuntimeError("no")

    collector = SnapshotCollector(lambda: str(tmp_path))
    collector.add_extra("pressure", lambda: {"pegged": True, "throttled": 3})
    collector.add_extra("can", lambda: None)
    collector.add_extra("bad", boom)
    collector.add_extra("load", lambda: {"x": 1})
    snap = collector.collect(install_id="i", label="l", app_version="1", reserve={}, restrictions={}, capabilities=[], hid_idle=None)
    assert snap["pressure"] == {"pegged": True, "throttled": 3} and snap["throttled"] == 3
    assert "can" not in snap and "bad" not in snap
    assert "cores" in snap["load"], "an extra never replaces a core key"
    bare = SnapshotCollector(lambda: str(tmp_path)).collect(install_id="i", label="l", app_version="1", reserve={}, restrictions={},
                                                            capabilities=[], hid_idle=None)
    assert bare["throttled"] == 0 and "pressure" not in bare
