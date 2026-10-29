
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

pytest.importorskip("fastapi")

from tests.python.computers.test_join_commit import JOIN, MAIN, Side, world  # noqa: F401, E402

from src.core.computers import commit  # noqa: E402
from src.core.computers.commit import JoinRefused  # noqa: E402
from src.core.computers.runtime import LazyPack  # noqa: E402
from src.core.pack.machines import config_state, settings_doc, settings_sign  # noqa: E402
from src.core.pack.machines.settings_custody import SettingsCustody  # noqa: E402
from src.core.pack.skills import alerts  # noqa: E402
from src.core.relay_identity.device_key import DeviceKey, b64url  # noqa: E402

A, B, C, R = "install-a", "install-b", "install-c", "install-r"
KEYS = {iid: DeviceKey.from_seed(bytes([i + 11]) * 32) for i, iid in enumerate((A, B, C, R))}


def custody(path: Path, me: str, keys: Dict[str, DeviceKey], default_master: str = A) -> SettingsCustody:
    path.write_text("{}")
    pub = {iid: b64url(k.raw_pub) for iid, k in keys.items()}
    signing = settings_sign.Signing(install_id=me, load_key=lambda: keys[me],
                                    pinned_key=lambda iid: pub.get(iid) if iid != me else None)
    return SettingsCustody(install_id=me, state=config_state.ConfigState(lambda: path), default_master=lambda: default_master,
                           signing=signing, paired=lambda: True)


def signed(signer: str, doc: settings_doc.PackSettings, keys: Dict[str, DeviceKey] = KEYS) -> tuple:
    return doc.model_dump(mode="json"), settings_sign.sign(doc, keys[signer], signer).to_dict()


def follower_of(path: Path, me: str, alpha: SettingsCustody, keys: Dict[str, DeviceKey]) -> SettingsCustody:
    held = custody(path, me, keys, default_master=alpha.install_id)
    doc, sig = alpha.outgoing()
    held.state.save_settings(settings_doc.from_dict(doc), sig, signed_mode=True)
    return held




def _routes(actions: Any) -> List[str]:
    out: List[str] = []
    for action in actions or ():
        if "route" in action:
            out.append(action["route"])
        out.extend(_routes(action.get("actions")))
    return out


def test_h1_refused_change_alert_never_offers_to_adopt_the_signer(tmp_path, monkeypatch):
    raised: List[Dict[str, Any]] = []
    monkeypatch.setattr(alerts.service, "raise_alert", lambda key, **kw: raised.append({"key": key, **kw}) or {"id": 1})
    a = custody(tmp_path / "a.json", A, KEYS)
    a.ensure_alpha_signed()
    alerts.configure(alerts.Seams(A, lambda: (a.settings().master_install_id, "", 0), lambda _i: "", lambda _i: True))
    a.refused = alerts.settings_refused_hook
    try:
        doc, sig = signed(C, settings_doc.PackSettings(master_install_id=C, rev=(99, C)))
        assert a.merge(doc, sig, C) is False
        assert [r["key"] for r in raised] == [alerts.REFUSED_PREFIX + C]
        assert "/pack/master" not in _routes(raised[0]["actions"])
        assert all(action.get("method") is None for action in raised[0]["actions"])
        doc, sig = signed(C, settings_doc.PackSettings(master_install_id=C, rev=(100, C)))
        assert a.merge(doc, sig, C) is False
        assert len(raised) == 1
        assert a.settings().master_install_id == A
    finally:
        alerts.configure(None)




def _joiner_pack(join: Side, keys: Dict[str, DeviceKey]) -> tuple:
    held = custody(join.config, JOIN, keys, default_master=JOIN)
    held.ensure_alpha_signed()
    assert held.state.signed_mode() and held.settings().master_install_id == JOIN
    pack = LazyPack(lambda: SimpleNamespace(runtime=SimpleNamespace(custody=held, settings=held.settings)))
    return held, pack


def _join_with(main: Side, join: Side, pack: Any, settings: Dict[str, Any]) -> None:
    asyncio.run(commit.joiner_provisional(join.open_db, join.links, identity=join.identity, own_iid=JOIN,
                                          main=main.peer_id("gm", "air"), own_grant_id="gj", kind="new", settings=settings,
                                          addresses=[], link_port=47110, pack=pack))


def test_h2_join_never_signs_main_document_as_the_joiners_own_edit(world, tmp_path):
    main, join = world
    keys = {**KEYS, JOIN: join.key, MAIN: main.key}
    held, pack = _joiner_pack(join, keys)
    before = held.outgoing()
    k = follower_of(tmp_path / "k.json", B, held, keys)
    forged = settings_doc.PackSettings(master_install_id=C, rev=(10**9, JOIN)).model_dump(mode="json")
    with pytest.raises(JoinRefused):
        _join_with(main, join, pack, forged)
    assert held.outgoing() == before
    k.merge(*held.outgoing(), JOIN)
    assert k.settings().master_install_id == JOIN
    legit = settings_doc.PackSettings(master_install_id=MAIN, rev=(7, MAIN))
    _join_with(main, join, pack, legit.model_dump(mode="json"))
    doc, sig = held.outgoing()
    assert doc["master_install_id"] == MAIN and sig is None
    assert k.merge(doc, sig, JOIN) is False and k.settings().master_install_id == JOIN


def test_h2_adopt_never_signs_even_a_document_naming_this_computer_as_editor(tmp_path):
    a = custody(tmp_path / "a.json", A, KEYS)
    a.ensure_alpha_signed()
    foreign = settings_doc.PackSettings(master_install_id=C, rev=(10**9, A))
    a.adopt(foreign)
    assert a.outgoing() == (foreign.model_dump(mode="json"), None)
    minted = a.mint({"auto_distribute": True}, strict=True)
    assert a.outgoing()[1]["signer"] == A and minted.rev[1] == A




def test_m1_unsigned_plant_cannot_make_a_member_the_first_trusted_signer(tmp_path):
    r = custody(tmp_path / "r.json", R, KEYS)
    assert r.merge(settings_doc.PackSettings(master_install_id=C, rev=(50, C)).model_dump(mode="json"), None, C) is True
    assert r.settings().master_install_id == C
    assert r.merge(*signed(C, settings_doc.PackSettings(master_install_id=C, rev=(51, C))), C) is True
    assert r.state.signed_mode() is False
    assert r.state.tofu_anchor() == A
    assert r.merge(*signed(A, settings_doc.PackSettings(master_install_id=A, rev=(30, A))), A) is True
    assert r.state.signed_mode() is True and r.settings().master_install_id == A
    assert r.merge(*signed(C, settings_doc.PackSettings(master_install_id=C, rev=(99, C))), C) is False
    assert r.merge(settings_doc.PackSettings(master_install_id=C, rev=(99, C)).model_dump(mode="json"), None, C) is False
    assert r.settings().master_install_id == A


def test_m1_honest_alpha_change_during_the_window_still_merges_and_the_owner_can_move_the_anchor(tmp_path):
    r = custody(tmp_path / "r.json", R, KEYS)
    assert r.merge(settings_doc.PackSettings(master_install_id=B, rev=(3, A)).model_dump(mode="json"), None, A) is True
    assert r.merge(*signed(B, settings_doc.PackSettings(master_install_id=B, auto_distribute=True, rev=(4, B))), B) is True
    assert r.settings().auto_distribute is True and r.state.signed_mode() is False
    assert r.outgoing()[1]["signer"] == B
    r.mint({"master_install_id": B}, strict=True)
    assert r.state.tofu_anchor() == B
    assert r.merge(*signed(B, settings_doc.PackSettings(master_install_id=B, rev=(9, B))), B) is True
    assert r.state.signed_mode() is True
