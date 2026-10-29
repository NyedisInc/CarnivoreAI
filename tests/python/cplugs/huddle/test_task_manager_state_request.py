
from __future__ import annotations

import asyncio
import json

import pytest

from src.core.mcp import pending, tools
from src.cplugs.huddle import service
from tests.python.cplugs.huddle.test_task_manager_focus import CALLER, add, client, setup  # noqa: F401

BASE = "/api/v1/cplugs/huddle"
TOOL = "task_manager_state_request"


@pytest.fixture(autouse=True)
def fresh_inbox(monkeypatch):
    monkeypatch.setattr(pending, "_store", pending.PendingActions())
    monkeypatch.setattr(pending, "MAX_WAIT_SECONDS", 0.05)


def ask(setup, args, caller=CALLER) -> dict:
    result = asyncio.run(tools.call_tool(setup.manager, caller, TOOL, args))
    return {"error": result["content"][0]["text"]} if result.get("isError") else json.loads(result["content"][0]["text"])


def state_of(client, item) -> str:
    return client.get(f"{BASE}/items/{item}").json()["state"]


def thread_of(client, item) -> list:
    return [m["text"] for m in client.get(f"{BASE}/items/{item}").json()["thread"]]


def approved_item(client) -> int:
    item = add(client, "12", "ship the thing")
    assert client.patch(f"{BASE}/items/{item}", json={"approved": True}).status_code == 200
    assert state_of(client, item) == "done"
    return item


def owner_decides(approve: bool) -> None:
    store = pending.get_store()
    row = store.list()[0]
    asyncio.run(store.approve(row["id"])) if approve else store.deny(row["id"])


def test_reopen_waits_for_the_owner_then_applies_and_records_a_message(client, setup):
    item = approved_item(client)
    answer = ask(setup, {"item": item, "action": "reopen", "reason": "the fix regressed"})
    assert answer["status"] == "pending"
    assert state_of(client, item) == "done"
    [card] = pending.get_store().list()
    assert card["action"] == TOOL and card["args"]["from_state"] == "done" and card["args"]["to_state"] == "open"
    assert "ship the thing" in card["args"]["title"] and "the fix regressed" in card["args_summary"]
    owner_decides(True)
    assert state_of(client, item) == "open"
    assert any("approved claude's request to reopen" in t and "the fix regressed" in t for t in thread_of(client, item))


def test_reopen_to_waiting_install_and_close_ends_approved(client, setup):
    item = approved_item(client)
    ask(setup, {"item": item, "action": "reopen", "to_state": "waiting", "reason": "needs a reinstall"})
    owner_decides(True)
    assert state_of(client, item) == "waiting"
    other = add(client, "12", "stale item")
    assert ask(setup, {"item": other, "action": "close", "reason": "duplicate of another"})["status"] == "pending"
    assert state_of(client, other) == "open"
    owner_decides(True)
    assert state_of(client, other) == "done"


def test_deny_leaves_the_item_and_says_so_on_it(client, setup):
    item = approved_item(client)
    ask(setup, {"item": item, "action": "reopen", "reason": "please"})
    owner_decides(False)
    assert state_of(client, item) == "done"
    assert any("denied claude's request to reopen" in t for t in thread_of(client, item))
    assert pending.get_store().list() == []


def test_a_second_request_refreshes_the_one_card_and_its_reason(client, setup):
    item = approved_item(client)
    ask(setup, {"item": item, "action": "reopen", "reason": "first reason"})
    first = pending.get_store().list()[0]["id"]
    ask(setup, {"item": item, "action": "reopen", "reason": "better reason"})
    rows = pending.get_store().list()
    assert [r["id"] for r in rows] == [first] and rows[0]["args"]["reason"] == "better reason"
    owner_decides(True)
    assert any("better reason" in t for t in thread_of(client, item)) and not any("first reason" in t for t in thread_of(client, item))


def test_each_item_gets_its_own_card(client, setup):
    a, b = approved_item(client), approved_item(client)
    ask(setup, {"item": a, "action": "reopen", "reason": "r"})
    ask(setup, {"item": b, "action": "reopen", "reason": "r"})
    assert len(pending.get_store().list()) == 2


def test_refusals_file_no_card(client, setup):
    open_item, done = add(client, "12", "plain"), approved_item(client)
    for args in ({"item": open_item, "action": "reopen", "reason": "r"},
                 {"item": done, "action": "close", "reason": "r"},
                 {"item": done, "action": "reopen", "reason": "  "},
                 {"item": done, "action": "reopen", "to_state": "done", "reason": "r"},
                 {"item": done, "action": "delete", "to_state": "open", "reason": "r"},
                 {"item": 9999, "action": "reopen", "reason": "r"},
                 {"item": done, "action": "reopen", "reason": "r", "state": "open"}):
        assert "error" in ask(setup, args), args
    assert pending.get_store().list() == []


def test_the_item_changing_before_approval_applies_nothing(client, setup):
    item = approved_item(client)
    ask(setup, {"item": item, "action": "reopen", "reason": "r"})
    assert client.patch(f"{BASE}/items/{item}", json={"approved": False}).status_code == 200
    client.patch(f"{BASE}/items/{item}", json={"approved": True})
    client.patch(f"{BASE}/items/{item}", json={"state": "todo"})
    owner_decides(True)
    assert state_of(client, item) == "todo"
    assert any("not applied" in t for t in thread_of(client, item))


def test_a_read_only_token_cannot_ask(client, setup):
    from src.core.mcp.caller import AgentCaller

    item = approved_item(client)
    assert "error" in ask(setup, {"item": item, "action": "reopen", "reason": "r"}, AgentCaller("x", "x", "x", "tok", "read"))
    assert pending.get_store().list() == []


def test_a_direct_update_of_an_approved_item_stays_refused_and_points_to_the_tool(client, setup):
    item = approved_item(client)
    result = asyncio.run(tools.call_tool(setup.manager, CALLER, "task_manager_update", {"item": item, "state": "open"}))
    assert result["isError"] and TOOL in result["content"][0]["text"]
    assert state_of(client, item) == "done"
    result = asyncio.run(tools.call_tool(setup.manager, CALLER, "task_manager_update", {"item": item, "state": "working"}))
    assert result["isError"] and TOOL in result["content"][0]["text"]


def test_the_owner_still_changes_states_himself(client, setup):
    item = approved_item(client)
    assert client.patch(f"{BASE}/items/{item}", json={"approved": False}).status_code == 200
    assert state_of(client, item) == "open"


def test_the_tool_is_declared_and_always_waits(setup):
    import json as _json
    from pathlib import Path

    manifest = _json.loads((Path(service.__file__).parent / "cplug.json").read_text())
    assert TOOL in manifest["surfaces"]["mcp_tools"]
    assert TOOL in tools.cplug_mcp.INBOX_TOOLS and TOOL not in tools.BEAST_SCOPE_TOOLS


def _restored_after_upgrade(setup, shown: dict, tool_args: dict):
    from src.core.mcp.approvals import runtime as approval_runtime

    store = pending.get_store()
    app = setup.manager.app
    store.set_runtime(lambda item: approval_runtime.recheck(app, item), lambda item: approval_runtime.replay(app, item))
    item = store.get(store.list()[0]["id"])
    item.execute = None
    item.args = dict(item.args, **shown)
    item.tool_args = dict(item.tool_args, **tool_args)
    return store, item


@pytest.mark.parametrize("shown,tool_args,ends", [
    ({"from_state": "approved"}, {}, "open"),
    ({"from_state": "approved_with_note", "to_state": "waiting_install"}, {"to_state": "waiting_install"}, "waiting"),
])
def test_a_card_filed_before_the_renames_is_applied_when_approved_after_them(client, setup, shown, tool_args, ends):
    item = approved_item(client)
    assert ask(setup, {"item": item, "action": "reopen", "reason": "regressed", **tool_args})["status"] == "pending"
    store, restored = _restored_after_upgrade(setup, shown, tool_args)
    result = asyncio.run(store.approve(restored.id))
    assert result.status == pending.APPROVED, result.reason
    assert state_of(client, item) == ends


def test_a_delete_request_waits_for_the_owner_and_then_removes_the_item_for_good(client, setup):
    item = add(client, "12", "throwaway")
    answer = ask(setup, {"item": item, "action": "delete", "reason": "a test item"})
    assert answer["status"] == "pending" and state_of(client, item) == "open"
    [card] = pending.get_store().list()
    assert card["args"]["to_state"] == "deleted" and card["args"]["action"] == "delete"
    assert TOOL in tools.cplug_mcp.INBOX_TOOLS and TOOL not in tools.BEAST_SCOPE_TOOLS
    owner_decides(True)
    assert item not in [i["id"] for i in client.get(f"{BASE}/lists/12").json()["items"]]


def test_a_denied_delete_request_leaves_the_item_and_says_so(client, setup):
    item = add(client, "12", "keep")
    ask(setup, {"item": item, "action": "delete", "reason": "tidy"})
    owner_decides(False)
    assert state_of(client, item) == "open"
    assert any("denied claude's request to delete" in t for t in thread_of(client, item))


def test_an_undo_completion_request_waits_for_the_owner_then_restores_and_sends_the_retraction(client, setup):
    item = approved_item(client)
    assert ask(setup, {"item": item, "action": "undo_completion", "reason": "he closed the wrong one"})["status"] == "pending"
    assert state_of(client, item) == "done"
    [card] = pending.get_store().list()
    assert card["args"]["action"] == "undo_completion" and card["args"]["to_state"] == "its prior state"
    owner_decides(True)
    assert state_of(client, item) == "open"
    assert "completion withdrawn" in thread_of(client, item)


def test_an_undo_completion_request_on_an_open_task_is_refused_and_after_a_move_applies_nothing(client, setup):
    open_item = add(client, "12", "still open")
    assert "not approved" in ask(setup, {"item": open_item, "action": "undo_completion", "reason": "x"})["error"]
    item = approved_item(client)
    ask(setup, {"item": item, "action": "undo_completion", "reason": "oops"})
    assert client.patch(f"{BASE}/items/{item}", json={"state": "open"}).status_code == 200
    owner_decides(True)
    assert state_of(client, item) == "open" and "completion withdrawn" not in thread_of(client, item)
