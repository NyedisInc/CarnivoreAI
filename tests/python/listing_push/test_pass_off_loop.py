
from __future__ import annotations

import asyncio
import sqlite3
import threading

from src.core import listing_gather
from tests.test_listing_off_the_loop import _manager_with, _status_rows


def _quiet(manager, monkeypatch) -> None:
    monkeypatch.setattr(manager, "_build_tmux_status_map", lambda: _status_rows(["cloude_a"]))
    monkeypatch.setattr(manager, "_instance_index_for_listing", lambda **_kw: None)
    monkeypatch.setattr(manager, "_label_for_tmux_name", lambda _n: None)
    monkeypatch.setattr(manager, "_identity_for_live_name", lambda _n: None)


def test_the_ownership_read_runs_off_the_event_loop(monkeypatch):
    manager = _manager_with([("ses_a", "cloude_a")])
    _quiet(manager, monkeypatch)
    seen: dict = {}

    def owned() -> set:
        seen["thread"] = threading.get_ident()
        return set()

    monkeypatch.setattr(manager._owned, "instances_from_db", owned)

    async def scenario():
        seen["loop"] = threading.get_ident()
        return await manager.list_session_infos()

    infos = asyncio.run(scenario())
    assert len(infos) == 1
    assert seen["thread"] != seen["loop"], "the ownership read ran on the event loop thread"


def test_one_gather_shares_one_reused_datastore_connection(monkeypatch):
    from src.core import session_manager as session_manager_module

    manager = _manager_with([("ses_a", "cloude_a"), ("ses_b", "cloude_b")])
    monkeypatch.setattr(manager, "_build_tmux_status_map", lambda: _status_rows(["cloude_a", "cloude_b"]))
    pooled = sqlite3.connect(":memory:")
    lends: list = []

    def lend(_state_dir):
        lends.append(pooled)
        return pooled

    def no_fresh_connection():
        raise AssertionError("a gather opened a fresh datastore connection instead of the reused one")

    monkeypatch.setattr(session_manager_module, "lend_for_state_dir", lend)
    monkeypatch.setattr(manager, "_writable_datastore_connection", no_fresh_connection)
    for _ in range(2):
        gathered = listing_gather.gather_listing_inputs(manager._listing_readers(), manager._listing_snapshot())
        assert gathered is not None
        assert getattr(manager._borrowed, "conn", None) is None, "the loan outlived the gather"
    assert len(lends) == 2, f"expected one loan per gather, got {len(lends)}"
    pooled.execute("select 1")
