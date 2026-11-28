
from __future__ import annotations

import asyncio
import base64
import sqlite3
from contextlib import closing
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("fastapi")

import src.config  # noqa: F401, E402
from fastapi import HTTPException  # noqa: E402

from src.api import pack_relay_approval_routes as routes  # noqa: E402
from src.core import resource_push  # noqa: E402
from src.core.db import connect  # noqa: E402
from tests.layouts_helpers import migrated  # noqa: E402
from src.core.computers import mesh_removal, store  # noqa: E402
from src.core.pack.machines import capabilities, roster_v2  # noqa: E402
from src.core.pack.machines import runtime as machines_runtime  # noqa: E402
from src.core.pack.relay import approval, login_gate, member_reach, removed_copies  # noqa: E402
from src.core.pack.relay import runtime as relay_runtime  # noqa: E402
from src.core.pack.relay.ddl import apply_pack_relay  # noqa: E402
from tests.python.pack.test_roster import _inputs  # noqa: E402
from tests.python.pack.test_settings_signing import IDS, PUB  # noqa: E402

A, B, C = IDS["a"], IDS["b"], IDS["c"]


def _wire(monkeypatch, tmp_path, lst: Any, me: str, content: str = A):
    custody = SimpleNamespace(held_lists=lambda: [lst, None] if lst is not None else [], content_alpha=lambda: content,
                              settings=lambda: SimpleNamespace(master_install_id=A))
    wired = SimpleNamespace(runtime=SimpleNamespace(install_id=me, custody=custody), peers=lambda: [SimpleNamespace(install_id=A, label="mac")])
    monkeypatch.setattr(machines_runtime, "wiring", lambda: wired)
    monkeypatch.setattr(store, "CACHE", SimpleNamespace(get=lambda iid: SimpleNamespace(transport="tls", inbound_control=1)))
    monkeypatch.setattr(member_reach, "member_ids", lambda: [i for i in (A, B) if i != me])
    monkeypatch.setattr(relay_runtime, "candidate_ids", lambda: [A] if me != A else [])
    monkeypatch.setattr(relay_runtime, "poll_owned_soon", lambda iid: None)
    monkeypatch.setattr(resource_push, "notify", lambda topic: None)
    monkeypatch.setattr(routes.global_wiring, "kick", lambda iid: None)
    db = tmp_path / "gate.db"

    def open_db() -> sqlite3.Connection:
        conn = sqlite3.connect(str(db))
        conn.isolation_level = None
        return conn
    with closing(open_db()) as conn:
        apply_pack_relay(conn)
    monkeypatch.setattr(routes, "open_db", open_db)
    return open_db


def _put(iid: str, answer: str) -> Any:
    return asyncio.run(routes.put_approval(iid, routes.ApprovalBody(answer=answer)))


def _rows(out: Any) -> dict:
    return {r["install_id"]: r for r in out["computers"]}


def test_the_card_on_a_member_and_the_name_of_a_removed_computer(monkeypatch, tmp_path):
    lst = roster_v2.plan_v2(None, _inputs(("a", "b", "c"), b={"may_receive_logins": True}), alpha=A)
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    open_db = _wire(monkeypatch, tmp_path, lst, C)
    card = routes._read()
    rows = _rows(card)
    assert card["covers_pack"] is False
    assert rows[A]["decided_by"] == "here" and rows[A]["pending"] is True and rows[A]["label"] == "mac"
    assert rows[B]["decided_by"] == "alpha" and rows[B]["alpha_yes"] is True and rows[B]["pending"] is False and rows[B]["answer"] is None and rows[B]["label"] == "b"
    assert _rows(_put(B, "no"))[B]["answer"] == "no"
    with closing(open_db()) as conn:
        assert approval.answers(conn) == {B: "no"}
    assert login_gate.decide(local="no", target=B, self_id=C, content_alpha=A, master=A, lst=lst, tls_row=True, caps=[capabilities.CAP_CREDENTIALS_MESH]) is False
    assert _rows(_put(B, "yes"))[B]["answer"] is None
    with closing(open_db()) as conn:
        assert approval.answers(conn) == {}
    assert _rows(_put(A, "yes"))[A]["answer"] == "yes"
    with pytest.raises(HTTPException) as err:
        _put("iid-stranger", "yes")
    assert err.value.status_code == 404
    custody = machines_runtime.wiring().runtime.custody
    custody.held_lists = lambda: (_ for _ in ()).throw(OSError("unreadable"))
    assert [r["install_id"] for r in routes._read()["computers"]] == [A] and routes._read()["covers_pack"] is False
    (tmp_path / "alpha").mkdir()
    _wire(monkeypatch, tmp_path / "alpha", lst, A)
    assert routes._read()["covers_pack"] is True
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    _wire(monkeypatch, tmp_path, lst, C)
    assert routes._read() == {"computers": [{"install_id": A, "label": "mac", "answer": "yes", "pending": False}]}
    with pytest.raises(HTTPException) as err:
        _put(B, "no")
    assert err.value.status_code == 404

    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    db = migrated(tmp_path / "state")

    def open_removal() -> sqlite3.Connection:
        return connect(db, create=False)
    with closing(open_removal()) as conn:
        conn.execute("CREATE TABLE pack_mesh_removal (install_id TEXT PRIMARY KEY, state TEXT NOT NULL, generation INTEGER NOT NULL, removed_at REAL, passes INTEGER NOT NULL DEFAULT 0, last_pass REAL)")
        conn.execute("INSERT INTO pack_mesh_removal (install_id, state, generation) VALUES ('old', 'listed', 1)")

    def lst_of(gen: int, *named: Any) -> roster_v2.RosterV2:
        comps = [roster_v2.RosterComputerV2(install_id=i, label=n, fed_public_key=PUB[A], cert=base64.b64encode(b"x" * 40).decode(), mesh=True) for i, n in named]
        return roster_v2.RosterV2(generation=gen, alpha="a", home="a", issued_at=1, computers=comps)
    held = {"lst": lst_of(2, ("a", "mac"), ("b", "me"), ("x", "laptop"))}
    removal = mesh_removal.Removal(open_removal, "b", mesh_removal.Steps(retire_from=None, end_jobs=None, records=None, notify=None), lambda: held["lst"], clock=lambda: 100.0)
    removal._write_plan()
    held["lst"] = lst_of(3, ("a", "mac"), ("b", "me"))
    removal._write_plan()
    held["lst"] = lst_of(4, ("a", "mac"), ("b", "me"))
    removal._write_plan()
    with closing(open_removal()) as conn:
        rows = mesh_removal.read_rows(conn)
        assert rows["x"].state == "removed" and rows["x"].label == "laptop" and rows["old"].label is None
        assert removed_copies.build(open_removal, None, 200_000)["computers"] == []
        assert sorted(c[0] for c in removed_copies.removed_computers(conn)) == ["old", "x"]
    with closing(open_removal()) as conn:
        apply_pack_relay(conn)
        conn.execute("INSERT INTO pack_relay_targets (account_key, target_profile, last_expiry_pushed, last_push_at, target_install_id) VALUES ('acct', 'p', 5, 50.0, 'x')")
        conn.commit()
    got = removed_copies.build(open_removal, None, 200_000)["computers"]
    assert [(c["install_id"], c["label"]) for c in got] == [("x", "laptop")]
