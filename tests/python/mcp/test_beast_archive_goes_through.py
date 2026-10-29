
from __future__ import annotations

import asyncio
import json

from src.core.mcp import beast_mode, pending
from tests.python.beast_mode.grid import arm as arm_beast
from tests.python.mcp.test_mcp_project_archive import PANE, _call, _rows, world  # noqa: F401


def _arm(monkeypatch) -> dict:
    switch = {"on": False}
    arm_beast(monkeypatch, lambda: switch["on"])
    return switch


def test_beast_resolves_an_archive_request_off_and_always_wait_keep_asking_and_arming_clears_a_pending_one(world, monkeypatch):
    db, ids = world
    switch = _arm(monkeypatch)
    store = pending.get_store()

    assert "pending" in str(_call("project_archive", {"project": ids["alpha"]}))
    assert [i["action"] for i in store.list()] == ["project_archive"] and _rows(db)[ids["alpha"]][2] is None

    switch["on"] = True
    assert asyncio.run(beast_mode.approve_pending()) == 1
    assert store.list() == [] and _rows(db)[ids["alpha"]][2] is not None
    assert [d["approval_source"] for d in store.decided()] == ["approved by beast mode"]

    answer = _call("project_archive", {"project": ids["beta"]})
    assert "pending" not in str(answer) and _rows(db)[ids["beta"]][2] is not None and store.list() == []
    assert {d["approval_source"] for d in store.decided()} == {"approved by beast mode"} and len(store.decided()) == 2

    assert _park_it("project_delete")["status"] == "pending"
    assert [i["action"] for i in store.list()] == ["project_delete"]


def _park_it(action: str, in_use: dict | None = None) -> dict:
    from types import SimpleNamespace

    from src.core.mcp import write_tools

    ran = []

    async def run(approved: bool) -> dict:
        ran.append(approved)
        return {"content": [{"type": "text", "text": "{\"ok\": true}"}]}

    manager = SimpleNamespace(gate_waited=True)
    answer = asyncio.run(write_tools.park(manager, PANE, "", "", action, action, {"n": 1}, run, dedupe_key=action, in_use=in_use))
    body = json.loads(answer["content"][0]["text"])
    return {"status": body.get("status", "ok"), "ran": ran}


def test_beast_lets_renames_moves_automations_and_mid_work_stops_through_but_deletes_and_computer_links_ask(world, monkeypatch):
    db, ids = world
    switch = _arm(monkeypatch)
    store = pending.get_store()
    busy = {"in_flight": True, "in_view": False, "signals": [{"key": "working", "params": {"source": "registry"}}], "status": "working"}
    through = ["project_move", "automation_create", "automation_run_now", "automation_update", "company_rename"]
    asks = ["session_delete", "project_delete", "automation_delete", "computer_add", "pack_gh_login_add", "computer_invite"]

    switch["on"] = False
    for action in through + ["project_rename", "session_stop"] + asks:
        monkeypatch.setattr(pending, "_store", pending.PendingActions())
        assert _park_it(action)["status"] == "pending", action
    monkeypatch.setattr(pending, "_store", pending.PendingActions())
    store = pending.get_store()

    switch["on"] = True
    assert "pending" not in str(_call("project_rename", {"project": ids["beta"], "name": "gamma"}))
    assert _rows(db)[ids["beta"]][0] == "gamma"
    for action in through:
        assert _park_it(action) == {"status": "ok", "ran": [True]}, action
    assert _park_it("session_stop", in_use=busy) == {"status": "ok", "ran": [True]}
    for action in asks[:5]:
        assert _park_it(action, in_use=busy)["status"] == "pending", action
    assert {d["approval_source"] for d in store.decided()} == {"approved by beast mode"}
    assert sorted(i["action"] for i in store.list()) == sorted(asks[:5])
    assert asyncio.run(beast_mode.approve_pending()) == 0


def _stored(store, action: str, **fields):
    async def execute() -> dict:
        return {"ok": True}

    item = store.create(caller_session_id="s", caller_tmux="t", target_session_id="", target_tmux="", action=action,
                        args_summary=action, execute=execute, args={"n": action}, dedupe_key=action, beast_eligible=False)
    for name, value in fields.items():
        setattr(item, name, value)
    return item


def test_arming_resolves_a_request_stored_before_the_widen_but_holds_deletes_and_typed_confirms(world, monkeypatch):
    _db, _ids = world
    switch = _arm(monkeypatch)
    store = pending.get_store()
    rename = _stored(store, "project_rename")
    _stored(store, "session_delete")
    _stored(store, "project_move", confirm_text="type the name")
    _stored(store, "session_send_keys")
    switch["on"] = True
    assert [i.id for i in store.beast_candidates()] == [rename.id]


def test_publish_repo_and_cplug_update_always_ask_even_armed(world, monkeypatch):
    switch = _arm(monkeypatch)
    switch["on"] = True
    assert not beast_mode.eligible_action("project_publish_repo") and not beast_mode.eligible_action("cplug_update")
    assert _park_it("project_publish_repo")["status"] == "pending"
