
from __future__ import annotations

import asyncio

from src.core.mcp import pending
from src.core.mcp.approvals import diff as approval_diff
from tests.python.automations.test_automation_api import CARD, View, _call, world  # noqa: F401

__all__ = ["world"]


def _parked():
    items = pending.get_store().list()
    assert len(items) == 1
    return items[0]


def test_edit_card_shows_before_and_after(world):
    made = world.store.create(name="weekly cards", cron="0 7 * * 1", target=CARD)
    _call(View(world.app), "automation_update", {"automation_id": made["automation_id"], "revision": 1, "cron": "0 9 * * 2",
                                                 "description": "tuesday now"})
    item = _parked()
    rows = {r["field"]: r for r in item["args"]["diff"]}
    assert set(rows) == {"trigger", "description"}
    assert rows["trigger"]["before"]["cron"] == "0 7 * * 1" and rows["trigger"]["after"]["cron"] == "0 9 * * 2"
    assert "'weekly cards'" in item["plain"] and "0 7 * * 1" in item["plain"] and "0 9 * * 2" in item["plain"]
    asyncio.run(pending.get_store().approve(item["id"]))
    assert world.store.get(made["automation_id"])["trigger"]["cron"] == "0 9 * * 2"


def test_stale_revision_is_refused_before_parking(world):
    made = world.store.create(name="n", cron="0 7 * * 1", target=CARD)
    world.store.update(made["automation_id"], 1, cron="0 8 * * 1")
    out = _call(View(world.app), "automation_update", {"automation_id": made["automation_id"], "revision": 1, "cron": "0 9 * * 1"})
    assert out.get("isError") and "revision_conflict" in out["content"][0]["text"]
    assert pending.get_store().list() == []


def test_delete_card_lists_everything_removed(world):
    made = world.store.create(name="doomed", cron="0 7 * * 1", target=CARD, description="goes away")
    _call(View(world.app), "automation_delete", {"automation_id": made["automation_id"]})
    item = _parked()
    rows = {r["field"]: r for r in item["args"]["diff"]}
    assert rows["name"]["before"] == "doomed" and rows["name"]["after"] is None and rows["description"]["before"] == "goes away"
    assert "'doomed'" in item["plain"] and "run history" in item["plain"]


def test_create_card_lists_every_field_and_the_diff_is_deterministic(world):
    args = {"name": "new one", "cron": "0 7 * * 1", "target": CARD}
    _call(View(world.app), "automation_create", args)
    rows = {r["field"]: r for r in _parked()["args"]["diff"]}
    assert rows["name"]["before"] is None and rows["name"]["after"] == "new one" and rows["trigger"]["after"]["cron"] == "0 7 * * 1"
    before = {"name": "a", "trigger": {"cron": "0 7 * * 1", "timezone": "local"}, "revision": 2}
    assert approval_diff.for_update(before, {"cron": "0 8 * * 1"}) == approval_diff.for_update(before, {"cron": "0 8 * * 1"})
    assert approval_diff.markdown([]) == ""
