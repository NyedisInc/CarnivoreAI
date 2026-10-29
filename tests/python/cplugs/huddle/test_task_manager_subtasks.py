
from __future__ import annotations

from src.core.mcp import tools
from tests.python.cplugs.huddle.test_task_manager_focus import add, call, client, setup  # noqa: F401


def test_a_parent_read_lists_its_live_forks_with_title_status_and_owner(client, setup):
    ok, parent = call(setup.manager, "task_manager_add", {"list": "all", "text": "ship the tabs"})
    ok, first = call(setup.manager, "task_manager_fork", {"item": parent["id"], "title": "write the test", "fork_state": "working", "lean": False})
    ok, second = call(setup.manager, "task_manager_fork", {"item": parent["id"], "title": "wire the route", "lean": False})
    ok, gone = call(setup.manager, "task_manager_fork", {"item": parent["id"], "title": "dropped", "lean": False})
    client.delete(f"/api/v1/cplugs/huddle/items/{gone['fork']['id']}")
    ok, read = call(setup.manager, "task_manager_tasks_list", {"item": parent["id"]})
    assert ok
    forks = read["item"]["forks"]
    assert [(f["id"], f["title"], f["status"]) for f in forks] == [
        (first["fork"]["id"], "write the test", "working"), (second["fork"]["id"], "wire the route", "open")]
    assert all(f["owner"] and f["list"] == "all" for f in forks)


def test_an_agent_updates_a_subtask_by_its_own_id(client, setup):
    ok, parent = call(setup.manager, "task_manager_add", {"list": "all", "text": "ship the tabs"})
    ok, made = call(setup.manager, "task_manager_fork", {"item": parent["id"], "title": "write the test", "lean": False})
    ok, done = call(setup.manager, "task_manager_update", {"item": made["fork"]["id"], "state": "review", "lean": False})
    assert ok and done["status"] == "review"
    ok, read = call(setup.manager, "task_manager_tasks_list", {"item": parent["id"]})
    assert [f["status"] for f in read["item"]["forks"]] == ["review"]


def test_an_item_with_no_forks_carries_none(client, setup):
    ok, plain = call(setup.manager, "task_manager_add", {"list": "all", "text": "alone"})
    ok, read = call(setup.manager, "task_manager_tasks_list", {"item": plain["id"]})
    assert "forks" not in read["item"]


def test_the_review_checks_tool_text_says_the_agent_sets_them_and_only_the_owner_ticks():
    update = next(d for d in tools.tool_definitions() if d["name"] == "task_manager_update")
    text = update["inputSchema"]["properties"]["review_checks"]["description"]
    assert "checklist" in text and "owner ticks" in text and "[]" in text
