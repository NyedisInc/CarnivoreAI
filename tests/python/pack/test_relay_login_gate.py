
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

import pytest

pytest.importorskip("fastapi")

import src.config  # noqa: F401, E402

from src.core.argent.pair_credential import CAP_CREDENTIAL, CredentialSender  # noqa: E402
from src.core.computers import store  # noqa: E402
from src.core.pack.machines import capabilities, roster_doc, roster_v2  # noqa: E402
from src.core.pack.machines import runtime as machines_runtime  # noqa: E402
from src.core.pack.relay import approval, login_gate  # noqa: E402
from src.core.pack.relay.ddl import apply_pack_relay  # noqa: E402
from tests.python.pack.test_roster import _inputs  # noqa: E402
from tests.python.pack.test_settings_signing import IDS  # noqa: E402

A, B, C = IDS["a"], IDS["b"], IDS["c"]
CAP = [capabilities.CAP_CREDENTIALS_MESH]


def _v2(**over: Any) -> roster_v2.RosterV2:
    return roster_v2.plan_v2(None, _inputs(("a", "b", "c"), **over), alpha=A)


def _decide(**kw: Any) -> bool:
    base = dict(local="yes", target=B, self_id=C, content_alpha=A, master=A, lst=_v2(b={"may_receive_logins": True}), tls_row=True, caps=CAP)
    base.update(kw)
    return login_gate.decide(**base)


def test_decide_table():
    assert _decide() is True
    assert _decide(local="no") is False
    assert _decide(lst=_v2(), local="yes") is False
    assert _decide(lst=_v2(b={"may_receive_logins": True, "one_way": True})) is False
    assert _decide(caps=[]) is False
    assert _decide(target="iid-removed", local="yes") is False
    assert _decide(lst=_v2(b={"may_receive_logins": True}).as_v1(), local="yes") is False
    assert _decide(self_id=A, target=B, lst=_v2(), local="yes") is True
    assert _decide(self_id=A, target=B, lst=_v2(), local=None) is False
    assert _decide(target=A, lst=_v2(), local="yes") is True
    assert _decide(self_id=A, content_alpha=None, master=A, lst=_v2(), local="yes") is False
    assert _decide(target="iid-ssh", tls_row=False, local="yes") is True
    assert _decide(lst=None, local="yes") is True and _decide(lst=None, local=None) is False


def _open_db(tmp_path: Path):
    def open_db() -> sqlite3.Connection:
        conn = sqlite3.connect(str(tmp_path / "gate.db"))
        conn.isolation_level = None
        return conn
    with open_db() as conn:
        apply_pack_relay(conn)
    return open_db


class _Custody:
    def __init__(self, held: Any) -> None:
        self.held, self.reads = held, 0

    def held_lists(self) -> Any:
        self.reads += 1
        return self.held

    def content_alpha(self) -> str:
        return A

    def settings(self) -> Any:
        return SimpleNamespace(master_install_id=A)


def _wire(monkeypatch, held: Any) -> _Custody:
    custody = _Custody(held)
    monkeypatch.setattr(machines_runtime, "wiring", lambda: SimpleNamespace(runtime=SimpleNamespace(install_id=C, custody=custody)))
    monkeypatch.setattr(store, "CACHE", SimpleNamespace(get=lambda iid: SimpleNamespace(transport="tls")))
    return custody


def test_gate_switch_off_equals_reader_and_switch_on_obeys_the_signed_list(tmp_path, monkeypatch):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    open_db = _open_db(tmp_path)
    with open_db() as conn:
        approval.record(conn, "y", "yes")
        approval.record(conn, "n", "no")
        approval.record(conn, B, "yes")
    plain = approval.reader(open_db)
    custody = _wire(monkeypatch, (_v2(b={"may_receive_logins": True}), None))
    gate = login_gate.gate(open_db, lambda iid: CAP)
    assert [gate(i) for i in ("y", "n", "unanswered")] == [plain(i) for i in ("y", "n", "unanswered")] == [True, False, False]
    assert custody.reads == 0

    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    assert gate(B) is True
    custody.held = (_v2(b={"may_receive_logins": True}).as_v1(), None)
    assert gate(B) is False
    custody.held = (_v2(), None)
    assert gate(B) is False
    with open_db() as conn:
        approval.record(conn, B, "no")
    custody.held, custody.reads = (_v2(b={"may_receive_logins": True}), None), 0
    assert gate(B) is False and custody.reads == 0


def test_a_no_from_the_gate_revokes_the_argent_delegate_and_mints_nothing():
    calls: List[str] = []

    class Delegates:
        async def revoke(self, iid: str) -> None:
            calls.append("revoke")

        async def mint(self, label: str) -> Any:
            calls.append("mint")
            raise AssertionError("no delegate may be minted for a member the list no longer approves")

    async def post(method: str, path: str, body: Any):
        calls.append("post")
        return 200, {}

    sender = CredentialSender(store=None, tokens=None, peer=lambda iid: (post, [CAP_CREDENTIAL]), candidates=lambda: [B],
                              allows=lambda iid: True, read_settings=lambda: None, approved=lambda iid: False, clock=lambda: 0.0,
                              delegates=Delegates(), label=lambda iid: "x")
    assert asyncio.run(sender._push_one(B, {}, 0.0, False)) is False
    assert calls == ["revoke"] and sender.sent[B]["state"] == "not_accepting"
