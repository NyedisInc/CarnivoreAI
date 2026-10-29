
from __future__ import annotations

import asyncio
import json
from datetime import datetime

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from src.core.pack.machines import capabilities, config_state, exchange, restrictions, roster as roster_mod, settings_doc
from src.core.pack.machines.roster import PeerInfo
from src.core.pack.reserve import model as reserve_model

IDS = {"a": "install-a", "b": "install-b", "c": "install-c"}
LABELS = {"a": "mac", "b": "studio", "c": "third"}


class FakeCollector:

    def __init__(self, name: str) -> None:
        self.name = name
        self.hid = None

    def hid_idle_seconds(self, wanted: bool):
        return self.hid if wanted else None

    def collect(self, *, install_id, label, app_version, reserve, restrictions, capabilities, hid_idle, now=None):
        return {"v": 1, "install_id": install_id, "label": label, "app_version": app_version, "taken_at": 1.0,
                "specs": {"cores": 10, "mem_total_gb": 16.0}, "load": {"cores": 10, "load_1": 1.3, "cpu_percent": None,
                "memory_percent": 40.0, "disk_percent": 50.0, "mem_available_gb": 8.0}, "battery": None,
                "hid_idle_seconds": hid_idle, "toolchain": {"git": True}, "reserve": reserve, "restrictions": restrictions,
                "capabilities": capabilities, "throttled": 0, "agents": None}


@pytest.fixture()
def pack(tmp_path):
    capabilities.register(capabilities.CAP_MACHINE)
    machines: dict = {}
    notes: list = []

    def make(name: str) -> exchange.PackMachines:
        path = tmp_path / f"{name}.json"
        path.write_text("{}")
        others = [n for n in IDS if n != name]

        def connected():
            return [(IDS[o], post_to(name, o), ["pack.machine"]) for o in others]

        rt = exchange.PackMachines(
            install_id=IDS[name], label=LABELS[name], app_version="1.0", state=config_state.ConfigState(lambda p=path: p),
            collector=FakeCollector(name), default_master=lambda: IDS["a"], connected=connected,
            notify=lambda topic, key, every: notes.append((name, topic, key)),
            local_now=lambda: datetime(2026, 10, 10, 3, 0))
        rt.member_labels = lambda n=name: [{"install_id": IDS[x], "label": LABELS[x]} for x in IDS]
        return rt

    def post_to(caller: str, target: str):
        async def post(method, path, body):
            assert (method, path) == ("POST", exchange.EXCHANGE_PATH)
            return 200, await machines[target].serve_exchange(IDS[caller], LABELS[caller], json.loads(json.dumps(body)))
        return post

    for name in IDS:
        machines[name] = make(name)
    machines["notes"] = notes
    return machines


def peers_of(name: str):
    return [PeerInfo(IDS[o], LABELS[o], f"peer-{o}", "connected", ["pack.machine"]) for o in IDS if o != name]


def test_roster_lists_three_machines_master_marked_and_receiver_enforces_restriction(pack):
    a, b, c = pack["a"], pack["b"], pack["c"]

    async def mesh():
        for name, rt in (("a", a), ("b", b), ("c", c)):
            for peer, post, caps in rt._connected():
                assert await rt.beat(peer, post, caps) is True
    asyncio.run(mesh())

    view = a.view(peers_of("a"))
    assert [m["install_id"] for m in view["machines"]] == [IDS["a"], IDS["b"], IDS["c"]]
    assert view["master_install_id"] == IDS["a"] and view["disagreement"] is None
    marked = [m["label"] for m in view["machines"] if m["is_master"]]
    assert marked == ["mac"]
    assert all(m["state"] in ("self", "connected") for m in view["machines"])
    assert view["machines"][1]["snapshot"]["load"]["load_1"] == 1.3
    assert view["machines"][1]["snapshot"]["reserve"]["level"] == "away"
    assert ("a", "pack_machines", IDS["b"]) in pack["notes"]

    view_two = a.view([p for p in peers_of("a") if p.install_id != IDS["c"]])
    third = [m for m in view_two["machines"] if m["install_id"] == IDS["c"]][0]
    assert third["state"] == "not_paired" and third["snapshot"] is None

    b.edit_settings({"master_install_id": IDS["b"], "auto_distribute": True})
    asyncio.run(mesh())
    for rt in (a, b, c):
        doc = rt.settings()
        assert doc.master_install_id == IDS["b"] and doc.auto_distribute is True and tuple(doc.rev) == (1, IDS["b"])
    assert [m["is_master"] for m in a.view(peers_of("a"))["machines"]] == [False, True, False]
    stale = settings_doc.default_doc(IDS["a"])
    assert a._merge_remote(stale.model_dump(mode="json")) is False

    c.set_restrictions({"max_agents": 0}, from_peer=False)
    app_c, app_a = FastAPI(), FastAPI()
    for app in (app_c, app_a):
        @app.post("/body", dependencies=[Depends(restrictions.require_peer_allowed(restrictions.ACTION_HOST_AGENTS))])
        async def body_request():
            return {"hosted": True}

    config_state._default = c.state
    refused = TestClient(app_c).post("/body")
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "pack_restricted" and refused.json()["detail"]["rule"] == "max_agents"
    config_state._default = a.state
    assert TestClient(app_a).post("/body").json() == {"hosted": True}
    config_state._default = None

    with pytest.raises(PermissionError):
        c.set_restrictions({"max_agents": 5}, from_peer=True)
    assert restrictions.Restrictions().may_receive_credentials is False
    assert "credentials" not in restrictions.scopes_for(a.state.restrictions(), tracks_master=True)
    with pytest.raises(PermissionError):
        a.set_restrictions({"may_receive_credentials": True}, from_peer=True)
    assert "credentials" in restrictions.scopes_for(a.set_restrictions({"may_receive_credentials": True}, from_peer=False), tracks_master=True)


def test_reserve_level_follows_schedule_then_keyboard():
    cfg = reserve_model.ReserveConfig()
    noon, night = datetime(2026, 10, 10, 12, 0), datetime(2026, 10, 10, 3, 0)
    assert reserve_model.active(cfg, noon, None) == {"level": "in_use", "cpu_pct": 30, "mem_pct": 20, "source": "schedule"}
    assert reserve_model.active(cfg, night, None)["level"] == "away"
    held = reserve_model.merged(cfg, {"keyboard_rule": {"enabled": True, "idle_minutes": 10}})
    assert reserve_model.active(held, night, 60.0) == {"level": "in_use", "cpu_pct": 30, "mem_pct": 20, "source": "keyboard"}
    assert reserve_model.active(held, night, 3600.0)["level"] == "away"
    assert reserve_model.active(held, night, None)["level"] == "away"
    wrap = reserve_model.merged(cfg, {"schedule": {"in_use_from": "22:00", "in_use_to": "06:00"}})
    assert reserve_model.in_schedule(wrap, night) and not reserve_model.in_schedule(wrap, noon)
