
from __future__ import annotations

from contextlib import closing
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

pytest.importorskip("fastapi")

from src.core.pack.machines import capabilities, roster_v2  # noqa: E402
from src.core.pack.machines import runtime as machines_runtime  # noqa: E402
from src.core.pack.relay import approval, runtime as relay_runtime  # noqa: E402
from tests.python.pack import test_mesh_screens_9c2 as sc  # noqa: E402
from tests.python.pack.test_roster import _inputs  # noqa: E402


def _rig(monkeypatch, tmp_path):
    lst = roster_v2.plan_v2(None, _inputs(("a", "b", "c"), b={"may_receive_logins": True}), alpha=sc.A)
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    open_db = sc._wire(monkeypatch, tmp_path, lst, sc.C)
    wired = machines_runtime.wiring()
    wired.peers = lambda: [SimpleNamespace(install_id=sc.A, label="mac"), SimpleNamespace(install_id=sc.B, label="b")]
    monkeypatch.setattr(relay_runtime, "candidate_ids", lambda: [sc.A, sc.B])
    return open_db, wired.runtime.custody


def test_s3_a_second_custody_read_that_fails_cannot_store_a_yes(monkeypatch, tmp_path):
    open_db, custody = _rig(monkeypatch, tmp_path)
    sc._put(sc.B, "yes")
    with closing(open_db()) as conn:
        assert approval.answers(conn) == {}
    good = custody.held_lists
    calls = {"n": 0}

    def second_read_fails():
        calls["n"] += 1
        if calls["n"] > 1:
            raise OSError("unreadable the second time")
        return good()

    custody.held_lists = second_read_fails
    sc._put(sc.B, "yes")
    with closing(open_db()) as conn:
        assert approval.answers(conn) == {}


def test_s4_an_unreadable_list_answers_a_code_and_stores_nothing_and_the_switch_off_is_unchanged(monkeypatch, tmp_path):
    open_db, custody = _rig(monkeypatch, tmp_path)
    custody.held_lists = lambda: (_ for _ in ()).throw(OSError("unreadable"))
    custody.settings = lambda: SimpleNamespace(master_install_id=sc.A)
    with pytest.raises(HTTPException) as refused:
        sc._put(sc.B, "yes")
    assert (refused.value.status_code, refused.value.detail["code"]) == (409, "relay_list_unreadable")
    assert "OSError" not in str(refused.value.detail)
    with closing(open_db()) as conn:
        assert approval.answers(conn) == {}
    assert sc._put(sc.B, "no")["computers"]
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    sc._put(sc.B, "yes")
    with closing(open_db()) as conn:
        assert approval.answers(conn) == {sc.B: "yes"}
