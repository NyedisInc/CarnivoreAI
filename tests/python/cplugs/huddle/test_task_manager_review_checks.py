
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.core.mcp import tools
from src.core.work.storage import WorkStorage
from src.cplugs.huddle.rules import CLAUDE, JOE, TaskManagerForbidden
from src.cplugs.huddle.store import TaskManagerStore
from src.cplugs.huddle import review_checks
from tests.python.cplugs.huddle.test_task_manager_focus import add, call, client, setup  # noqa: F401

BASE = "/api/v1/cplugs/huddle"


def labels(item: dict) -> list:
    return [c["label"] for c in item["review_checks"]]


def test_an_item_with_no_checks_carries_an_empty_list(client, setup):
    item = add(client, "all", "plain")
    assert client.get(f"{BASE}/lists/all").json()["items"][0]["review_checks"] == [] and item


def test_the_agent_sets_checks_with_review_and_they_come_back_unticked(client, setup):
    ok, made = call(setup.manager, "task_manager_add", {"list": "all", "text": "built it"})
    ok, done = call(setup.manager, "task_manager_update", {"item": made["id"], "state": "review", "review_checks": ["tests pass", " open the row ", "looks right"]})
    assert ok and done["status"] == "review"
    assert [(c["id"], c["label"], c["checked"], c["checked_at"], c["checked_by"]) for c in done["review_checks"]] == [
        ("c1", "tests pass", False, None, None), ("c2", "open the row", False, None, None), ("c3", "looks right", False, None, None)]
    ok, listed = call(setup.manager, "task_manager_tasks_list", {"list": "all", "fields": ["review"]})
    assert [c["label"] for c in listed["items"][0]["review_checks"]] == ["tests pass", "open the row", "looks right"]
    assert client.get(f"{BASE}/lists/all").json()["items"][0]["review_checks"][0]["label"] == "tests pass"


def test_the_owner_ticks_and_unticks_one_check_and_the_tick_is_saved_and_pushed(client, setup):
    item = add(client, "all", "ship")
    client.patch(f"{BASE}/items/{item}", json={"state": "review", "review_checks": ["a", "b"]})
    setup.published.clear()
    before = client.get(f"{BASE}/lists/all").json()["items"][0]
    ticked = client.patch(f"{BASE}/items/{item}/review-checks/c2", json={"checked": True})
    assert ticked.status_code == 200
    checks = ticked.json()["review_checks"]
    assert [c["checked"] for c in checks] == [False, True] and checks[1]["checked_by"] == "joe" and checks[1]["checked_at"]
    assert ticked.json()["revision"] == before["revision"] + 1 and ticked.json()["seq"] > before["seq"]
    assert "cplug.huddle.list:all" in setup.published
    assert [c["checked"] for c in client.get(f"{BASE}/lists/all").json()["items"][0]["review_checks"]] == [False, True]
    unticked = client.patch(f"{BASE}/items/{item}/review-checks/c2", json={"checked": False}).json()["review_checks"]
    assert unticked[1]["checked"] is False and unticked[1]["checked_at"] is None and unticked[1]["checked_by"] is None


def test_a_tick_to_the_state_a_check_already_has_changes_nothing(client, setup):
    item = add(client, "all", "ship")
    client.patch(f"{BASE}/items/{item}", json={"review_checks": ["a"]})
    first = client.patch(f"{BASE}/items/{item}/review-checks/c1", json={"checked": True}).json()
    setup.published.clear()
    again = client.patch(f"{BASE}/items/{item}/review-checks/c1", json={"checked": True}).json()
    assert again["revision"] == first["revision"] and setup.published == []


def test_a_new_list_replaces_the_old_one_and_resets_the_ticks_and_an_empty_list_clears(client, setup):
    item = add(client, "all", "ship")
    client.patch(f"{BASE}/items/{item}", json={"review_checks": ["a", "b"]})
    client.patch(f"{BASE}/items/{item}/review-checks/c1", json={"checked": True})
    replaced = client.patch(f"{BASE}/items/{item}", json={"review_checks": ["x"]}).json()
    assert labels(replaced) == ["x"] and replaced["review_checks"][0]["checked"] is False
    kept = client.patch(f"{BASE}/items/{item}", json={"state": "review"}).json()
    assert labels(kept) == ["x"]
    assert client.patch(f"{BASE}/items/{item}", json={"review_checks": []}).json()["review_checks"] == []


def test_bad_check_input_is_refused(client, setup):
    item = add(client, "all", "ship")
    assert client.patch(f"{BASE}/items/{item}", json={"review_checks": ["  "]}).status_code == 400
    assert client.patch(f"{BASE}/items/{item}", json={"review_checks": ["x" * (review_checks.MAX_LABEL + 1)]}).status_code == 400
    assert client.patch(f"{BASE}/items/{item}", json={"review_checks": ["a"] * (review_checks.MAX_CHECKS + 1)}).status_code == 400
    client.patch(f"{BASE}/items/{item}", json={"review_checks": ["a"]})
    assert client.patch(f"{BASE}/items/{item}/review-checks/c9", json={"checked": True}).status_code == 404
    assert client.patch(f"{BASE}/items/999/review-checks/c1", json={"checked": True}).status_code == 404
    assert client.patch(f"{BASE}/items/{item}/review-checks/c1", json={"checked": "yes"}).status_code == 422


def test_only_the_owner_ticks_and_the_route_needs_auth(client, setup, tmp_path):
    item = add(client, "all", "ship")
    client.patch(f"{BASE}/items/{item}", json={"review_checks": ["a"]})
    setup.app.dependency_overrides.clear()
    with TestClient(setup.app) as anonymous:
        assert anonymous.patch(f"{BASE}/items/{item}/review-checks/c1", json={"checked": True}).status_code in (401, 403)
    store = TaskManagerStore(WorkStorage(tmp_path / "own"), notify=lambda t: None)
    mine = store.add("all", "x", actor=CLAUDE)["id"]
    store.update(mine, actor=CLAUDE, state="review", review_checks=["a"])
    with pytest.raises(TaskManagerForbidden):
        store.tick_review_check(mine, "c1", True, actor=CLAUDE)
    assert store.tick_review_check(mine, "c1", True, actor=JOE)["review_checks"][0]["checked"] is True


def test_the_mcp_parity_the_agent_sets_checks_and_has_no_tick_tool():
    update = next(d for d in tools.tool_definitions() if d["name"] == "task_manager_update")
    schema = update["inputSchema"]["properties"]["review_checks"]
    assert schema["type"] == "array" and schema["items"]["type"] == "string"
    assert "review_checks" not in update["inputSchema"].get("required", [])
    names = {d["name"] for d in tools.tool_definitions()}
    assert not {n for n in names if "check" in n and n.startswith(("task_manager", "huddle"))}
