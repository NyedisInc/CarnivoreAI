
from __future__ import annotations

import asyncio
import json

import pytest

from src.core.mcp import pending, write_tools
from src.core.mcp.approvals import call_context
from src.cplugs.host import runtime
from src.cplugs.huddle import legacy_approvals, lifecycle, rules, service
from tests.python.cplugs.huddle.test_task_manager_focus import CALLER, add, client, setup  # noqa: F401

LIST = "/api/v1/cplugs/huddle/lists"


@pytest.fixture
def store(monkeypatch):
    fresh = pending.PendingActions()
    monkeypatch.setattr(pending, "_store", fresh)
    return fresh


def park(setup, args=None, ran=None):
    async def run(_approved: bool) -> dict:
        (ran if ran is not None else []).append("bookmark_branch")
        return {"content": [{"type": "text", "text": json.dumps({"label": "after alpha"})}]}

    async def go():
        sent = args if args is not None else {"bookmark": 7, "huddle_item": 1}
        stripped = call_context.strip_legacy_arg("bookmark_branch", sent, call_context.GATED_TOOLS)
        with call_context.calling("bookmark_branch", stripped):
            return await write_tools.park(setup.manager, CALLER, "", "", "bookmark_branch", "open a new session from the bookmark",
                                          stripped, run, dedupe_key="bookmark_branch:7")

    out = json.loads(asyncio.run(go())["content"][0]["text"])
    assert out["status"] == "pending"
    return pending.get_store().get(out["id"])


def all_items(client):
    return client.get(f"{LIST}/all").json()["items"]


def test_an_approval_reaches_the_queue_and_creates_nothing_in_the_huddle(client, setup, store):
    target = add(client, "all", "branch the bookmark")
    before = client.get(f"{LIST}/all").json()
    ran: list = []
    item = park(setup, ran=ran)
    assert [r["id"] for r in pending.get_store().list()] == [item.id]
    assert "huddle_item" not in item.as_dict() and "task_manager_tasks_list" not in item.as_dict()
    after = client.get(f"{LIST}/all").json()
    assert [i["id"] for i in after["items"]] == [i["id"] for i in before["items"]] == [target]
    row = after["items"][0]
    assert "approvals" not in row and row["needs_action"] is None and row["thread"] == [] and row["unread"] == before["items"][0]["unread"]
    assert all(i["title"] != "claude's approvals" for i in after["items"]) and ran == []


def test_the_owner_decision_runs_it_and_approval_wait_resolves_with_no_huddle_post(client, setup, store):
    target = add(client, "all", "branch the bookmark")
    ran: list = []
    item = park(setup, ran=ran)
    asyncio.run(pending.get_store().approve(item.id))
    assert ran == ["bookmark_branch"] and pending.get_store().get(item.id).status == pending.APPROVED
    assert asyncio.run(pending.wait_for(pending.get_store().get(item.id), 1)) == pending.APPROVED
    row = next(i for i in all_items(client) if i["id"] == target)
    assert row["thread"] == [] and "approvals" not in row and len(all_items(client)) == 1


def test_a_denied_action_leaves_the_huddle_untouched(client, setup, store):
    item = park(setup)
    pending.get_store().deny(item.id)
    assert pending.get_store().get(item.id).status == pending.DENIED
    assert all_items(client) == []


def test_a_waiting_approval_never_makes_an_item_need_you():
    assert lifecycle.needs_action("working", None, None) is None
    assert not hasattr(rules, "APPROVALS_KEY") and not hasattr(rules, "SYSTEM_HOLDER_KEYS")


def test_legacy_holder_items_are_soft_deleted_once_on_every_list(client, setup):
    store = service.store(runtime.current().context("huddle", background=True))
    keep = add(client, "all", "real work")
    holders = [store.add(key, "actions claude asked to run", actor=rules.CLAUDE, title="claude's approvals",
                         created_key=legacy_approvals.HOLDER_KEY)["id"] for key in ("all", "12")]
    assert legacy_approvals.retire_holders(store) == holders
    assert legacy_approvals.retire_holders(store) == []
    for key in ("all", "12"):
        assert [i["title"] for i in client.get(f"{LIST}/{key}").json()["items"] if i["title"] == "claude's approvals"] == []
    assert any(i["id"] == keep for i in all_items(client))
    for item_id in holders:
        assert store.deleted_item(item_id)["deleted"] is True
