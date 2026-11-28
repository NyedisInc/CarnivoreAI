from __future__ import annotations

import asyncio
import contextlib
import copy
import json
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest
from fastapi import HTTPException

# ruff: noqa: E402
from src.api import federation_pack_machine_routes as fed_routes
from src.api import pack_machines_routes as routes
from src.core.computers import direction
from src.core.federation import peer_links
from src.core.pack.machines import capabilities as caps, config_state, exchange, operating, settings_doc, settings_sign
from src.core.pack.machines.roster_v2 import RosterComputerV2, RosterV2
from src.core.pack.machines.settings_sign import Signing
from src.core.pack.meshdata import envelope, gossip, hlc, ops_kind, wire
from src.core.pack.meshdata.store import RecordStore
from src.core.relay_identity.device_key import DeviceKey, b64url
import base64

CERT = base64.b64encode(b"x" * 40).decode()
NOW = 1_800_000_000_000
AUTHORITY_KEYS = ["master_install_id", "alpha", "successors", "one_way", "may_receive_logins", "reserve", "may_host_agents", "skills", "global_setup",
                  "in_use", "away", "schedule", "keyboard_rule", "may_receive_credentials", "max_agents", "t:iid:may_host_agents", "rev"]


class Net:

    def __init__(self, tmp: Path, *names: str, alpha: str = "a") -> None:
        self.now, self.alpha, self.one_way, self.off_list, self.no_mesh = NOW, alpha, set(), set(), set()
        self.iid = {n: str(uuid.uuid4()) for n in names}
        self.keys = {n: DeviceKey.from_seed(bytes([i + 3]) * 32) for i, n in enumerate(names)}
        self.signing = {n: Signing(install_id=self.iid[n], load_key=lambda n=n: self.keys[n], pinned_key=lambda iid: None) for n in names}
        self.stores = {n: RecordStore(tmp / f"{n}-mesh.db", self.iid[n], wall=lambda: self.now, signing=self.signing[n]) for n in names}
        self.names = names

    def lst(self) -> RosterV2:
        rows = [RosterComputerV2(install_id=self.iid[n], label=n, fed_public_key=b64url(self.keys[n].raw_pub), cert=CERT, mesh=True, one_way=n in self.one_way,
                                capabilities=[] if n in self.no_mesh else [caps.CAP_MESH])
                for n in self.names if n not in self.off_list]
        return RosterV2(generation=1, alpha=self.iid[self.alpha], home=self.iid[self.alpha], issued_at=1, computers=rows)

    def write(self, name: str, **changes: Any) -> int:
        self.use(name)
        return operating.write_own(changes)

    def use(self, name: str) -> None:
        self.active = SimpleNamespace(store=self.stores[name], signing=self.signing[name], held_list=self.lst, wake=lambda: None)
        gossip.ACTIVE = self.active

    def sync(self, src: str, dst: str) -> None:
        lst = self.lst()

        async def call(body: dict) -> dict:
            answer, _ = wire.handle_sync(self.stores[dst], json.loads(json.dumps(body)), self.iid[src], lst, self.now)
            return json.loads(json.dumps(answer))
        asyncio.run(wire.run_sync(self.stores[src], call, lst, self.iid[dst], lambda: self.now))

    def both(self, x: str, y: str, rounds: int = 2) -> None:
        for _ in range(rounds):
            self.sync(x, y)
            self.sync(y, x)

    def forged(self, signer: str, key: str, value: Any, kind: str = "ops", stamp_ms: Optional[int] = None) -> Dict[str, Any]:
        stamp = [stamp_ms or self.now + 5, 0, self.iid[signer]]
        sig = envelope.sign(envelope.KIND_RECORD, f"{kind}:{key}", stamp, envelope.body_hash(value), self.signing[signer])
        return {f"{kind}:{key}": {"v": value, "s": stamp, "sig": sig.to_dict()}}

    def rows(self, name: str) -> Dict[str, Any]:
        return self.stores[name].kind_rows(self.lst(), "ops")

    def eff(self, name: str, doc: Optional[settings_doc.PackSettings] = None) -> settings_doc.PackSettings:
        self.use(name)
        operating.CURRENT, operating._DIGEST = {}, None
        operating.refresh(self.stores[name], self.lst())
        return operating.effective(doc or settings_doc.default_doc(self.iid[self.alpha]))


@pytest.fixture()
def net(tmp_path, monkeypatch):
    monkeypatch.setattr(caps, "MESH_BUILD_ON", True)
    monkeypatch.setattr(direction, "contained", lambda iid: False)
    monkeypatch.setattr(direction, "one_way_ids", lambda: [])
    monkeypatch.setattr(gossip, "STEPS", [])
    monkeypatch.setattr(gossip, "ACTIVE", None)
    monkeypatch.setattr(operating, "CURRENT", {})
    monkeypatch.setattr(operating, "_DIGEST", None)
    monkeypatch.setattr(peer_links, "LINKS", None)
    monkeypatch.setattr(gossip, "STORE_PATH", None)
    return lambda *names, **kw: Net(tmp_path, *names, **kw)


def machines(tmp: Path, n: Net, name: str, master: Optional[str] = None) -> exchange.PackMachines:
    path = tmp / f"{name}-config.json"
    path.write_text("{}")
    return exchange.PackMachines(install_id=n.iid[name], label=name, app_version="1.0", state=config_state.ConfigState(lambda: path), collector=None,
                                 default_master=lambda: n.iid[master or n.alpha], connected=lambda: [], notify=lambda *a: None,
                                 signing=n.signing[name], paired=lambda: True)


def run_step(rt: Any, n: Net, name: str) -> None:
    n.use(name)
    asyncio.run(operating.step(rt)(SimpleNamespace(store=n.stores[name], signing=n.signing[name]), n.lst()))


def test_a_record_naming_an_authority_field_is_refused_from_every_origin_and_every_forwarder(net):
    n = net("a", "b", "c")
    for key in AUTHORITY_KEYS:
        for signer in ("b", "a"):
            for forwarder in ("a", "b"):
                out = n.stores["c"].offer_batch(n.forged(signer, key, "x"), n.iid[forwarder], n.lst(), n.now)
                assert (out.accepted, out.refused) == (0, 1), (key, signer, forwarder)
    bad_model = n.forged("b", "placement_model", {"connection": "c", "model": "m", "extra": 1})
    assert n.stores["c"].offer_batch(bad_model, n.iid["b"], n.lst(), n.now).accepted == 0
    assert n.stores["c"].offer_batch(n.forged("b", "auto_distribute", 1), n.iid["b"], n.lst(), n.now).accepted == 0
    assert n.stores["c"].offer_batch(n.forged("b", "placement_mode", "anything"), n.iid["b"], n.lst(), n.now).accepted == 0
    assert n.rows("c") == {}
    assert n.stores["c"].offer_batch(n.forged("b", "auto_distribute", True), n.iid["b"], n.lst(), n.now).accepted == 1


def test_restrictions_never_ride_a_record_and_the_control_path_refuses_a_peer_loosening(net, tmp_path):
    n = net("a", "b")
    for key in ("may_install_tools", "restrictions", "t:iid:may_host_agents", "allowed_projects", "max_agents"):
        assert n.stores["a"].offer_batch(n.forged("b", key, False), n.iid["b"], n.lst(), n.now).accepted == 0
    rt = machines(tmp_path, n, "a")
    rt.set_restrictions({"may_install_tools": False}, from_peer=True)
    with pytest.raises(PermissionError):
        rt.set_restrictions({"may_install_tools": True}, from_peer=True)
    assert rt.state.restrictions().may_install_tools is False
    rt.set_restrictions({"may_install_tools": True}, from_peer=False)
    assert rt.state.restrictions().may_install_tools is True


def test_a_reserve_never_rides_a_record_and_a_member_cannot_set_it_over_the_control_path(net, monkeypatch):
    n = net("a", "b")
    for key in ("reserve", "in_use", "away", "schedule", "keyboard_rule"):
        for signer in ("a", "b"):
            assert n.stores["a"].offer_batch(n.forged(signer, key, {"x": 1}), n.iid[signer], n.lst(), n.now).accepted == 0
    who = {"alpha": n.iid["a"]}
    runtime = SimpleNamespace(content_alpha=lambda: who["alpha"], set_reserve=lambda patch: SimpleNamespace(model_dump=lambda: {"ok": True}))
    monkeypatch.setattr(fed_routes, "_wired", lambda: SimpleNamespace(runtime=runtime))

    def call(peer: str) -> Any:
        principal = SimpleNamespace(is_peer=True, grant=SimpleNamespace(peer_install_id=n.iid[peer]))
        return asyncio.run(fed_routes.put_reserve(SimpleNamespace(patch={}), principal))
    with pytest.raises(HTTPException) as refused:
        call("b")
    assert refused.value.status_code == 403 and refused.value.detail["code"] == "pack_reserve_alpha_only"
    assert call("a") == {"reserve": {"ok": True}}


def test_a_one_way_origin_is_refused_and_its_route_edit_is_not_alpha(net, monkeypatch):
    n = net("a", "b", "c")
    n.one_way.add("b")
    assert n.stores["c"].offer_batch(n.forged("b", "auto_distribute", True), n.iid["b"], n.lst(), n.now).accepted == 0
    doc = settings_doc.default_doc(n.iid["a"])
    runtime = SimpleNamespace(install_id=n.iid["b"], settings=lambda: doc)
    monkeypatch.setattr(routes, "_wired", lambda: SimpleNamespace(runtime=runtime))
    n.use("b")
    with pytest.raises(HTTPException) as refused:
        asyncio.run(routes.put_settings(routes.SettingsBody(auto_distribute=True), None))
    assert refused.value.status_code == 409 and refused.value.detail["code"] == "not_alpha" and refused.value.detail["alpha"] == n.iid["a"]


def test_rows_held_then_the_list_flips_the_origin_one_way_prune_drops_them(net):
    n = net("a", "b", "c")
    n.write("b", auto_distribute=True)
    n.both("b", "c")
    assert "auto_distribute" in n.rows("c")
    n.one_way.add("b")
    assert n.stores["c"].prune(n.lst()) >= 1
    assert n.rows("c") == {} and "ops:auto_distribute" not in n.stores["c"].servable(n.lst())


def test_a_contained_origin_is_stored_but_never_applied(net, monkeypatch):
    n = net("a", "b", "c")
    n.write("b", auto_distribute=True)
    n.both("b", "c")
    monkeypatch.setattr(direction, "contained", lambda iid: iid == n.iid["b"])
    assert n.rows("c") == {}
    base = settings_doc.default_doc(n.iid["a"])
    assert n.eff("c", base) is base


def test_a_removed_origin_is_dropped_with_its_floor_and_cannot_come_back(net):
    n = net("a", "b", "c")
    n.write("b", auto_distribute=True)
    entry = None
    n.both("b", "c")
    entry = copy.deepcopy(n.stores["c"].servable(n.lst())["ops:auto_distribute"])
    n.off_list.add("b")
    n.stores["c"].reconcile(n.lst())
    assert n.rows("c") == {}
    assert n.stores["c"].offer_batch({"ops:auto_distribute": entry}, n.iid["a"], n.lst(), n.now).accepted == 0


def test_an_old_signed_value_cannot_be_replayed_over_a_newer_one(net):
    n = net("a", "b", "c")
    n.write("b", auto_distribute=True)
    n.both("b", "c")
    old = copy.deepcopy(n.stores["c"].servable(n.lst())["ops:auto_distribute"])
    n.write("b", auto_distribute=False)
    n.both("b", "c")
    out = n.stores["c"].offer_batch({"ops:auto_distribute": old}, n.iid["a"], n.lst(), n.now)
    assert out.accepted == 0 and out.stale == 1
    assert n.rows("c")["auto_distribute"][0] is False


def test_two_computers_changing_different_fields_at_once_both_keep_their_change(net):
    n = net("a", "b", "c")
    n.write("b", auto_distribute=True)
    n.write("c", placement_mode="enhanced")
    n.both("b", "c")
    for name in ("b", "c"):
        assert {k: v for k, (v, _s) in n.rows(name).items()} == {"auto_distribute": True, "placement_mode": "enhanced"}
        eff = n.eff(name)
        assert eff.auto_distribute is True and eff.placement_mode == "enhanced" and eff.master_install_id == n.iid["a"] and eff.rev == (0, n.iid["a"])


def test_with_the_alpha_down_a_members_change_reaches_d_through_the_interim_alpha_and_authority_stays_frozen(net, tmp_path):
    n = net("a", "b", "c", "d")
    n.write("b", auto_distribute=True, placement_model={"connection": "conn", "model": "m"})
    n.both("b", "c")
    n.both("c", "d")
    eff = n.eff("d")
    assert eff.auto_distribute is True and eff.placement_model.model == "m"
    doc_c = settings_doc.PackSettings(master_install_id=n.iid["c"], rev=(4, n.iid["c"]))
    edits: List[Any] = []
    interim = SimpleNamespace(install_id=n.iid["c"], content_alpha=lambda: None, settings=lambda: doc_c, edit_settings=edits.append,
                              settings_changed=lambda: None)
    run_step(interim, n, "c")
    assert edits == [] and doc_c.rev == (4, n.iid["c"])
    for name in ("c", "d"):
        out = n.stores[name].offer_batch(n.forged("b", "master_install_id", n.iid["b"]), n.iid["c"], n.lst(), n.now)
        assert (out.accepted, out.refused) == (0, 1)
        assert "master_install_id" not in n.rows(name)


def test_the_home_alpha_projects_a_record_once_signed_by_itself_and_never_loops(net, tmp_path):
    n = net("a", "b")
    rt = machines(tmp_path, n, "a")
    n.write("b", auto_distribute=True)
    n.sync("b", "a")
    run_step(rt, n, "a")
    doc = rt.settings()
    assert doc.rev == (1, n.iid["a"]) and doc.auto_distribute is True and doc.master_install_id == n.iid["a"]
    sig = settings_sign.signature_from(rt.state.settings_signature())
    assert sig.signer == n.iid["a"] and settings_sign.verify(doc, sig, n.signing["a"].public_key_for(n.iid["a"]))
    run_step(rt, n, "a")
    assert rt.settings().rev == (1, n.iid["a"])
    rt.edit_settings({"auto_distribute": False})
    assert rt.settings().rev == (2, n.iid["a"])
    run_step(rt, n, "a")
    assert rt.settings().auto_distribute is True and rt.settings().rev == (3, n.iid["a"])
    run_step(rt, n, "a")
    assert rt.settings().rev == (3, n.iid["a"])


def test_the_alphas_own_route_edit_writes_the_records_before_the_document(net, tmp_path, monkeypatch):
    n = net("a", "b")
    order: List[str] = []
    doc = settings_doc.default_doc(n.iid["a"])

    def edit(changes: Dict[str, Any]) -> None:
        order.append("document")
        assert n.rows("a")["auto_distribute"][0] is True

    runtime = SimpleNamespace(install_id=n.iid["a"], settings=lambda: doc, edit_settings=edit, settings_changed=lambda: order.append("notify"), kick=lambda: None)
    monkeypatch.setattr(routes, "_wired", lambda: SimpleNamespace(runtime=runtime))

    async def view() -> dict:
        return {}

    monkeypatch.setattr(routes, "machines_view", view)
    n.use("a")
    asyncio.run(routes.put_settings(routes.SettingsBody(auto_distribute=True), None))
    assert order == ["document"] and "auto_distribute" in n.rows("a")
    with pytest.raises(HTTPException) as bad:
        asyncio.run(routes.put_settings(routes.SettingsBody.model_construct(placement_mode="nope", model_fields_set={"placement_mode"}), None))
    assert bad.value.status_code == 422 and "placement_mode" not in n.rows("a")
    n.use("b")
    member = SimpleNamespace(install_id=n.iid["b"], settings=lambda: doc, edit_settings=edit, settings_changed=lambda: order.append("notify"), kick=lambda: None)
    monkeypatch.setattr(routes, "_wired", lambda: SimpleNamespace(runtime=member))
    order.clear()
    asyncio.run(routes.put_settings(routes.SettingsBody(placement_mode="enhanced"), None))
    assert order == ["notify"] and n.rows("b")["placement_mode"][0] == "enhanced"


def test_with_the_switch_off_a_member_gets_the_same_409_and_the_readers_see_the_document(net, tmp_path, monkeypatch):
    n = net("a", "b")
    n.write("b", auto_distribute=True)
    monkeypatch.setattr(caps, "MESH_BUILD_ON", False)
    doc = settings_doc.default_doc(n.iid["a"])
    runtime = SimpleNamespace(install_id=n.iid["b"], settings=lambda: doc)
    monkeypatch.setattr(routes, "_wired", lambda: SimpleNamespace(runtime=runtime))
    with pytest.raises(HTTPException) as refused:
        asyncio.run(routes.put_settings(routes.SettingsBody(auto_distribute=True), None))
    assert (refused.value.status_code, refused.value.detail) == (409, {"code": "not_alpha", "alpha": n.iid["a"],
                                                                      "detail": "pack settings are changed on alpha; change them there"})
    operating.CURRENT = {"auto_distribute": True}
    assert operating.effective(doc) is doc and operating.may_write(n.iid["b"]) is False
    rt = machines(tmp_path, n, "a")
    assert rt.operating_settings() == rt.settings()


def _alpha_route(n: Net, monkeypatch: Any, name: str = "a", **extra: Any) -> Any:
    doc = settings_doc.default_doc(n.iid["a"])
    seen: Dict[str, Any] = {"edits": [], "changed": 0, "edit_locked": [], "settings_locked": []}

    def edit(changes: Dict[str, Any]) -> None:
        seen["edits"].append(changes)
        seen["edit_locked"].append(operating.EDIT_LOCK.locked())

    def get_settings() -> Any:
        seen["settings_locked"].append(operating.EDIT_LOCK.locked())
        return doc

    def changed() -> None:
        seen["changed"] += 1

    runtime = SimpleNamespace(install_id=n.iid[name], settings=get_settings, edit_settings=edit, settings_changed=changed, kick=lambda: None, **extra)
    runtime.seen = seen
    monkeypatch.setattr(routes, "_wired", lambda: SimpleNamespace(runtime=runtime))

    async def view() -> dict:
        return {}

    monkeypatch.setattr(routes, "machines_view", view)
    return runtime


def _put(**body: Any) -> Any:
    return asyncio.run(routes.put_settings(routes.SettingsBody(**body), None))


def test_leaving_a_pack_wipes_the_store_the_floors_and_the_operating_values(net, tmp_path, monkeypatch):
    n = net("a", "b", "x")
    n.write("b", auto_distribute=True)
    n.sync("b", "a")
    old_id = n.stores["b"].store_id()
    rt = machines(tmp_path, n, "b")
    n.use("b")
    assert operating.CURRENT
    rt.custody.clear_roster()
    assert n.rows("b") == {} and n.stores["b"].store_id() != old_id and operating.CURRENT == {}
    with n.stores["b"]._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM floors").fetchone()[0] == 0 and conn.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 0
    n.sync("b", "x")
    assert n.rows("x") == {}


def test_leaving_a_pack_with_the_service_down_wipes_the_file(net, tmp_path):
    n = net("a", "b")
    n.write("b", auto_distribute=True)
    gossip.ACTIVE = None
    gossip.STORE_PATH = n.stores["b"].path
    rt = machines(tmp_path, n, "b")
    rt.custody.clear_roster()
    assert RecordStore(n.stores["b"].path, n.iid["b"]).kind_rows(n.lst(), "ops") == {}


def test_a_hand_over_and_a_switch_off_leave_never_wipe(net, tmp_path, monkeypatch):
    n = net("a", "b")
    n.write("b", auto_distribute=True)
    rt = machines(tmp_path, n, "b")
    rt.edit_settings({"master_install_id": n.iid["a"]})
    assert "auto_distribute" in n.rows("b")
    monkeypatch.setattr(caps, "MESH_BUILD_ON", False)
    rt.custody.clear_roster()
    assert "auto_distribute" in n.rows("b")


class _FakeStore:

    def __init__(self) -> None:
        self.locked: List[bool] = []

    def kind_digest(self, lst: Any, kind: str) -> str:
        self.locked.append(operating._LOCK.locked())
        return "d"

    def kind_rows(self, lst: Any, kind: str) -> Dict[str, Any]:
        self.locked.append(operating._LOCK.locked())
        return {}


def test_refresh_holds_its_lock_around_the_whole_read_and_assign(net):
    store = _FakeStore()
    operating.refresh(store, None)
    assert store.locked == [True, True]


def test_the_projection_and_the_route_edit_both_run_under_the_one_edit_lock(net, monkeypatch):
    n = net("a", "b")
    rt = _alpha_route(n, monkeypatch, content_alpha=lambda: n.iid["a"])
    operating.CURRENT = {"auto_distribute": True}
    operating._project(rt)
    assert rt.seen["edits"] and rt.seen["edit_locked"] == [True] and all(rt.seen["settings_locked"])
    rt.seen["edit_locked"].clear()
    rt.seen["settings_locked"].clear()
    n.use("a")
    _put(auto_distribute=True)
    assert rt.seen["edit_locked"] == [True]
    assert not operating.EDIT_LOCK.locked()


def test_an_alpha_edit_whose_record_could_not_be_signed_is_refused_and_the_document_is_not_touched(net, monkeypatch):
    n = net("a", "b")
    rt = _alpha_route(n, monkeypatch)
    n.use("a")
    monkeypatch.setattr(envelope, "try_sign", lambda *a, **k: None)
    with pytest.raises(HTTPException) as refused:
        _put(auto_distribute=True)
    assert refused.value.status_code == 409 and refused.value.detail["code"] == "ops_not_signed" and refused.value.detail["fields"] == ["auto_distribute"]
    assert rt.seen["edits"] == []


def test_an_alpha_edit_with_the_store_closed_is_refused_when_records_may_exist_else_it_goes_through(net, monkeypatch):
    n = net("a", "b")
    rt = _alpha_route(n, monkeypatch, held_list=n.lst)
    gossip.ACTIVE = None
    with pytest.raises(HTTPException) as refused:
        _put(auto_distribute=True)
    assert refused.value.status_code == 503 and refused.value.detail["code"] == "meshdata_unavailable" and rt.seen["edits"] == []
    rt.held_list = lambda: None
    _put(auto_distribute=True)
    assert len(rt.seen["edits"]) == 1


def test_a_member_put_that_signed_nothing_says_why_and_never_notifies(net, monkeypatch):
    n = net("a", "b")
    rt = _alpha_route(n, monkeypatch, "b")
    n.use("b")
    _put(auto_distribute=True)
    assert rt.seen["changed"] == 1
    with pytest.raises(HTTPException) as same:
        _put(auto_distribute=True)
    assert same.value.status_code == 409 and same.value.detail["code"] == "nothing_changed"
    monkeypatch.setattr(envelope, "try_sign", lambda *a, **k: None)
    with pytest.raises(HTTPException) as unsigned:
        _put(placement_mode="enhanced")
    assert unsigned.value.status_code == 409 and unsigned.value.detail["code"] == "ops_not_signed"
    assert rt.seen["changed"] == 1 and rt.seen["edits"] == []


def test_a_contained_peer_is_served_no_ops_rows(net, monkeypatch):
    n = net("a", "b", "c")
    n.write("a", auto_distribute=True)
    monkeypatch.setattr(direction, "contained", lambda iid: iid == n.iid["c"])
    assert any(k.startswith("ops:") for k in n.stores["a"].view(n.lst(), for_peer=n.iid["b"])[0])
    assert not any(k.startswith("ops:") for k in n.stores["a"].view(n.lst(), for_peer=n.iid["c"])[0])


def test_with_an_older_app_alpha_members_write_no_records_and_the_document_stands(net, monkeypatch):
    n = net("a", "b")
    n.no_mesh.add("a")
    n.write("b", auto_distribute=True)
    doc = settings_doc.default_doc(n.iid["a"])
    assert operating.may_write(n.iid["b"]) is False
    assert operating.effective(doc) is doc
    _alpha_route(n, monkeypatch, "b")
    with pytest.raises(HTTPException) as refused:
        _put(auto_distribute=True)
    assert refused.value.status_code == 409 and refused.value.detail["code"] == "not_alpha"


def test_an_alpha_whose_live_hello_lacks_the_capability_is_an_older_app_even_if_the_list_says_otherwise(net, monkeypatch):
    n = net("a", "b")
    n.write("b", auto_distribute=True)
    links = SimpleNamespace(client=lambda iid: object(), capabilities=lambda iid: [])
    monkeypatch.setattr(peer_links, "LINKS", links)
    doc = settings_doc.default_doc(n.iid["a"])
    assert operating.may_write(n.iid["b"]) is False and operating.effective(doc) is doc
    monkeypatch.setattr(peer_links, "LINKS", SimpleNamespace(client=lambda iid: object(), capabilities=lambda iid: [caps.CAP_MESH]))
    assert operating.may_write(n.iid["b"]) is True and operating.effective(doc).auto_distribute is True


def test_a_member_hiding_its_capability_freezes_nobody(net):
    n = net("a", "b", "c")
    n.no_mesh.add("c")
    n.write("b", auto_distribute=True)
    assert operating.may_write(n.iid["b"]) is True
    n.use("b")
    operating.refresh(n.stores["b"], n.lst())
    assert operating.effective(settings_doc.default_doc(n.iid["a"])).auto_distribute is True


class _RacyStore:

    def __init__(self) -> None:
        self.state = ("d1", {"auto_distribute": (False, None)})
        self.a_in, self.go, self._parked = threading.Event(), threading.Event(), False

    def kind_digest(self, lst: Any, kind: str) -> str:
        return self.state[0]

    def kind_rows(self, lst: Any, kind: str) -> Dict[str, Any]:
        rows = self.state[1]
        if not self._parked:
            self._parked = True
            self.a_in.set()
            self.go.wait(5)
        return rows


def _interleave(lock: Any, wait: float) -> "tuple[bool, Dict[str, Any]]":
    store = _RacyStore()
    saved = operating._LOCK
    operating._LOCK = lock
    try:
        a = threading.Thread(target=operating.refresh, args=(store, None))
        b_done = threading.Event()

        def run_b() -> None:
            try:
                operating.refresh(store, None)
            finally:
                b_done.set()

        b = threading.Thread(target=run_b)
        a.start()
        assert store.a_in.wait(5)
        store.state = ("d2", {"auto_distribute": (True, None)})
        b.start()
        blocked = not b_done.wait(wait)
        store.go.set()
        a.join(5)
        b.join(5)
        assert not a.is_alive() and not b.is_alive()
        return blocked, dict(operating.CURRENT)
    finally:
        operating._LOCK = saved


def test_two_refreshes_interleaved_never_leave_older_values(net):
    blocked, current = _interleave(operating._LOCK, 0.3)
    assert blocked and current == {"auto_distribute": True}
    operating.CURRENT, operating._DIGEST = {}, None
    blocked, current = _interleave(contextlib.nullcontext(), 5)
    assert not blocked and current == {"auto_distribute": False}
