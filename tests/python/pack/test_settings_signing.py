
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional

import pytest

pytest.importorskip("fastapi")

import src.config  # noqa: F401, E402
from fastapi import HTTPException  # noqa: E402
from pydantic import BaseModel, ConfigDict  # noqa: E402

from src.api import pack_machines_routes  # noqa: E402
from src.core.app_alerts import service  # noqa: E402
from src.core.db import db_path_for  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402
from src.core.pack.machines import capabilities, config_state, exchange, settings_doc, settings_sign  # noqa: E402
from src.core.pack.skills import alerts  # noqa: E402
from src.core.relay_identity.device_key import DeviceKey, b64url  # noqa: E402

IDS = {"a": "install-a", "b": "install-b", "c": "install-c"}
LABELS = {"a": "mac", "b": "hosta", "c": "third"}
KEYS = {n: DeviceKey.from_seed(bytes([i + 1]) * 32) for i, n in enumerate(IDS)}
PUB = {IDS[n]: b64url(KEYS[n].raw_pub) for n in IDS}
CAPS = ["pack.machine", capabilities.CAP_SETTINGS_SIGNED]


class FakeCollector:

    def hid_idle_seconds(self, wanted: bool) -> None:
        return None

    def collect(self, *, install_id, label, app_version, reserve, restrictions, capabilities, hid_idle, now=None) -> Dict[str, Any]:
        return {"v": 1, "install_id": install_id, "label": label, "app_version": app_version, "taken_at": 1.0, "specs": {},
                "load": {}, "battery": None, "hid_idle_seconds": None, "toolchain": {}, "reserve": reserve,
                "restrictions": restrictions, "capabilities": capabilities, "throttled": 0, "agents": None}


def make_pack(tmp_path: Path, signed: Dict[str, bool], caps: Optional[Dict[str, list]] = None) -> Dict[str, Any]:
    capabilities.register(capabilities.CAP_MACHINE, capabilities.CAP_SETTINGS_SIGNED)
    machines: Dict[str, Any] = {}
    refused: list = []

    def post_to(caller: str, target: str):
        async def post(method, path, body):
            assert (method, path) == ("POST", exchange.EXCHANGE_PATH)
            reply = await machines[target].serve_exchange(IDS[caller], LABELS[caller], json.loads(json.dumps(body)))
            return 200, json.loads(json.dumps(reply))
        return post

    for name in IDS:
        path = tmp_path / f"{name}.json"
        path.write_text("{}")
        others = [o for o in IDS if o != name]
        signing = settings_sign.Signing(install_id=IDS[name], load_key=lambda n=name: KEYS[n],
                                        pinned_key=lambda iid, n=name: PUB.get(iid) if iid != IDS[n] else None)
        rt = exchange.PackMachines(
            install_id=IDS[name], label=LABELS[name], app_version="1.0", state=config_state.ConfigState(lambda p=path: p),
            collector=FakeCollector(), default_master=lambda: IDS["a"],
            connected=lambda n=name, o=others: [(IDS[x], post_to(n, x), (caps or {}).get(x, CAPS)) for x in o],
            notify=lambda topic, key, every: None, local_now=lambda: datetime(2026, 10, 18, 12, 0),
            signing=signing if signed.get(name, True) else None, paired=lambda: True)
        rt.custody.refused = lambda sender, verdict, doc, n=name: refused.append((n, sender, verdict.outcome, doc.master_install_id))
        machines[name] = rt
    machines["refused"] = refused
    return machines


def mesh(pack: Dict[str, Any], rounds: int = 2) -> None:
    async def run():
        for _ in range(rounds):
            for name in IDS:
                for peer, post, caps in pack[name]._connected():
                    await pack[name].beat(peer, post, caps)
    asyncio.run(run())


def masters(pack: Dict[str, Any]) -> Dict[str, str]:
    return {n: pack[n].settings().master_install_id for n in IDS}


def held(rt: exchange.PackMachines) -> tuple:
    return rt.settings().model_dump(mode="json"), rt.state.settings_signature()


def test_first_beat_alpha_signs_and_a_legit_owner_change_on_alpha_propagates(tmp_path):
    pack = make_pack(tmp_path, {})
    mesh(pack)
    for n in IDS:
        assert pack[n].state.signed_mode() is True
        assert pack[n].state.settings_signature()["signer"] == IDS["a"]
    pack["a"].edit_settings({"master_install_id": IDS["b"]})
    mesh(pack)
    assert masters(pack) == {n: IDS["b"] for n in IDS}
    pack["b"].edit_settings({"auto_distribute": True})
    mesh(pack)
    assert all(pack[n].settings().auto_distribute is True for n in IDS)
    assert pack["refused"] == []


def test_forged_document_signed_by_a_non_alpha_peer_is_refused(tmp_path):
    pack = make_pack(tmp_path, {})
    mesh(pack)
    doc = settings_doc.edited(pack["c"].settings(), {"master_install_id": IDS["c"]}, IDS["c"])
    doc = settings_doc.PackSettings(**{**doc.model_dump(), "rev": (99, IDS["c"])})
    pack["c"].state.save_settings(doc, settings_sign.sign(doc, KEYS["c"], IDS["c"]).to_dict())
    mesh(pack)
    assert masters(pack) == {"a": IDS["a"], "b": IDS["a"], "c": IDS["c"]}
    assert {(n, s, o) for n, s, o, _m in pack["refused"]} == {("a", IDS["c"], "not_alpha"), ("b", IDS["c"], "not_alpha")}
    assert len(pack["refused"]) == 2
    pack["a"].edit_settings({"master_install_id": IDS["c"]})
    mesh(pack)
    assert masters(pack) == {n: IDS["c"] for n in IDS}


def test_replayed_older_or_equal_version_is_refused(tmp_path):
    pack = make_pack(tmp_path, {})
    mesh(pack)
    pack["a"].edit_settings({"master_install_id": IDS["b"]})
    mesh(pack)
    old_doc, old_sig = held(pack["b"])
    pack["b"].edit_settings({"auto_distribute": True})
    mesh(pack)
    now_doc, now_sig = held(pack["c"])
    assert tuple(now_doc["rev"]) > tuple(old_doc["rev"])
    assert pack["c"]._merge_remote(old_doc, IDS["a"], old_sig) is False
    assert pack["c"].settings().auto_distribute is True
    assert pack["c"]._merge_remote(now_doc, IDS["a"], now_sig) is False
    pack["b"].edit_settings({"auto_distribute": False})
    new_doc, new_sig = held(pack["b"])
    assert pack["c"]._merge_remote(new_doc, IDS["b"], new_sig) is True


def test_tampered_field_fails_verification(tmp_path):
    pack = make_pack(tmp_path, {"b": True})
    mesh(pack)
    pack["a"].edit_settings({"auto_distribute": True})
    doc, sig = held(pack["a"])
    for field, value in (("master_install_id", IDS["c"]), ("auto_distribute", False), ("placement_mode", "enhanced")):
        tampered = {**doc, field: value}
        assert pack["b"]._merge_remote(tampered, IDS["c"], sig) is False, field
    assert pack["b"].settings().master_install_id == IDS["a"]
    assert {o for _n, _s, o, _m in pack["refused"]} == {"bad_signature"}
    forged = {**sig, "sig": KEYS["c"].sign(settings_sign.signed_bytes(settings_doc.from_dict(doc)))}
    assert pack["b"]._merge_remote(doc, IDS["c"], forged) is False
    assert pack["b"]._merge_remote(doc, IDS["c"], {**sig, "signer": IDS["c"]}) is False
    assert pack["b"]._merge_remote(doc, IDS["a"], sig) is True
    assert pack["b"].settings().auto_distribute is True


def test_tofu_migration_keeps_unsigned_merging_until_alpha_signs_then_refuses_with_an_alert(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    assert ensure_db_migrated(state_dir).status == "ok"
    service.configure(db_path_for(state_dir), None)
    try:
        pack = make_pack(tmp_path, {"a": False, "b": False, "c": True})
        alerts.configure(alerts.Seams(IDS["c"], lambda: (pack["c"].settings().master_install_id, "", 0),
                                      lambda iid: {IDS[n]: LABELS[n] for n in IDS}.get(iid, ""), lambda _i: True))
        c = pack["c"]
        c.custody.refused = alerts.settings_refused_hook
        legacy = settings_doc.PackSettings(master_install_id=IDS["a"], auto_distribute=True, rev=(4, IDS["b"]))
        assert c._merge_remote(legacy.model_dump(mode="json"), IDS["b"]) is True
        assert c.state.signed_mode() is False and c.settings().auto_distribute is True
        mesh(pack, rounds=1)
        assert all(pack[n].settings().auto_distribute is True for n in IDS)
        rogue = settings_doc.PackSettings(master_install_id=IDS["b"], rev=(5, IDS["b"]))
        assert c._merge_remote(rogue.model_dump(mode="json"), IDS["b"], settings_sign.sign(rogue, KEYS["b"], IDS["b"]).to_dict()) is False
        assert c.state.signed_mode() is False
        pack["a"].custody.signing = settings_sign.Signing(install_id=IDS["a"], load_key=lambda: KEYS["a"], pinned_key=PUB.get)
        mesh(pack, rounds=1)
        assert c.state.signed_mode() is True and c.state.settings_signature()["signer"] == IDS["a"]
        assert c.settings().auto_distribute is True
        counter = c.settings().rev[0]
        unsigned = settings_doc.PackSettings(master_install_id=IDS["b"], rev=(counter + 5, IDS["b"]))
        assert c._merge_remote(unsigned.model_dump(mode="json"), IDS["b"]) is False
        assert c.settings().master_install_id == IDS["a"]
        found = service.list_view(Path(service._db_path), include_closed=True, limit=50)["alerts"]
        keys = [r["key"] for r in found]
        assert keys == [alerts.REFUSED_PREFIX + IDS["b"]]
        assert c._merge_remote(c.settings().model_dump(mode="json"), IDS["b"]) is False
        assert len(service.list_view(Path(service._db_path), include_closed=True, limit=50)["alerts"]) == 1
    finally:
        alerts.configure(None)
        service.configure(None, None)


class OldExchangeBody(BaseModel):

    model_config = ConfigDict(extra="forbid")

    snapshot: Dict[str, Any]
    settings: Optional[Dict[str, Any]] = None
    want_agents: bool = False


def test_signature_is_sent_only_to_a_peer_that_advertises_it(tmp_path):
    pack = make_pack(tmp_path, {}, caps={IDS["b"]: ["pack.machine"]})
    a = pack["a"]
    a.custody.ensure_alpha_signed()
    sent: list = []

    async def old_peer(method, path, body):
        OldExchangeBody(**body)
        sent.append(body)
        return 200, {"snapshot": {**body["snapshot"], "install_id": IDS["b"], "label": "hosta"}, "settings": None}

    async def new_peer(method, path, body):
        sent.append(body)
        return 200, {"snapshot": {**body["snapshot"], "install_id": IDS["c"], "label": "third"}, "settings": None}

    assert asyncio.run(a.beat(IDS["b"], old_peer, ["pack.machine"])) is True
    assert asyncio.run(a.beat(IDS["c"], new_peer, CAPS)) is True
    assert "settings_sig" not in sent[0]
    assert sent[1]["settings_sig"]["signer"] == IDS["a"]


def test_settings_route_answers_not_alpha_off_alpha(tmp_path, monkeypatch):
    pack = make_pack(tmp_path, {})
    mesh(pack)
    for name, expect in (("b", 409), ("a", 200)):
        rt = pack[name]
        rt.kick = lambda: None
        monkeypatch.setattr(pack_machines_routes, "_wired", lambda rt=rt: SimpleNamespace(runtime=rt, peers=lambda: []))
        body = pack_machines_routes.SettingsBody(auto_distribute=True)
        if expect == 409:
            with pytest.raises(HTTPException) as caught:
                asyncio.run(pack_machines_routes.put_settings(body, None))
            assert caught.value.status_code == 409 and caught.value.detail["code"] == "not_alpha"
            assert rt.settings().auto_distribute is False
        else:
            asyncio.run(pack_machines_routes.put_settings(body, None))
            assert rt.settings().auto_distribute is True


def test_tofu_takes_the_alphas_first_signed_document_even_below_a_legacy_counter():
    signing = settings_sign.Signing(install_id=IDS["c"], load_key=lambda: KEYS["c"], pinned_key=PUB.get)
    legacy_held = settings_doc.PackSettings(master_install_id=IDS["a"], rev=(9, IDS["b"]))
    first = settings_doc.PackSettings(master_install_id=IDS["a"], rev=(2, IDS["a"]))
    sig = settings_sign.sign(first, KEYS["a"], IDS["a"])

    def verdict(signed_mode: bool, signature=sig, doc=first) -> str:
        return settings_sign.judge(held=legacy_held, remote=doc, signature=signature, self_id=IDS["c"], signed_mode=signed_mode,
                                   anchor=IDS["a"], public_key_for=signing.public_key_for).outcome

    assert verdict(False) == settings_sign.ACCEPT_TOFU
    assert verdict(True) == settings_sign.IGNORE
    other = settings_doc.PackSettings(master_install_id=IDS["b"], rev=(2, IDS["b"]))
    assert verdict(False, settings_sign.sign(other, KEYS["b"], IDS["b"]), other) == settings_sign.IGNORE
