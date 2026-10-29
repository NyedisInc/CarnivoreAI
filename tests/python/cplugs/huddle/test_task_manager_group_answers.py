
from __future__ import annotations

from tests.python.cplugs.huddle.test_task_manager_focus import add, call, client, setup  # noqa: F401

LIST = "/api/v1/cplugs/huddle/lists/12"


def numbers(client) -> dict:
    return {i["id"]: i["number"] for i in client.get(LIST).json()["items"]}


def test_move_into_a_group_answers_the_recomputed_number(client, setup):
    ids = [add(client, "12", f"item {n}") for n in range(10)]
    ok, start = call(setup.manager, "task_manager_tasks_list", {"list": "12"})
    assert ok
    cursor = start["cursor"]
    for n, item in enumerate(ids):
        ok, moved = call(setup.manager, "task_manager_move", {"item": item, "group": "auth" if n % 2 else "sidebar"})
        assert ok, moved
        assert moved["number"] == numbers(client)[item], (n, moved)
    ok, changed = call(setup.manager, "task_manager_changes", {"list": "12", "since": cursor})
    assert ok
    assert sorted(g["name"] for g in changed["groups"]) == ["auth", "sidebar"]
    shown = numbers(client)
    assert {i["id"]: i["number"] for i in changed["items"]} == shown
    assert sorted(shown.values()) == list(range(1, 11))


def test_changes_answer_only_the_groups_stamped_after_the_cursor_unless_it_is_a_reset(client, setup):
    item = add(client, "12", "file me")
    assert call(setup.manager, "task_manager_group_create", {"list": "12", "name": "build"})[0]
    ok, start = call(setup.manager, "task_manager_tasks_list", {"list": "12"})
    assert call(setup.manager, "task_manager_move", {"item": item, "group": "build"})[0]
    ok, changed = call(setup.manager, "task_manager_changes", {"list": "12", "since": start["cursor"]})
    assert ok and changed["groups"] == [] and changed["items"][0]["group"] is not None
    for scope in ({}, {"list": "12"}):
        ok, everything = call(setup.manager, "task_manager_changes", {"since": 0, **scope})
        assert ok and [g["name"] for g in everything["groups"]] == ["build"]


def test_all_projects_shows_a_new_empty_group_even_in_a_list_with_no_items(client, setup):
    made = client.post("/api/v1/cplugs/huddle/lists/12/groups", json={"name": "widgets"})
    assert made.status_code == 200
    assert "cplug.huddle.list:12" in setup.published
    groups = client.get("/api/v1/cplugs/huddle/aggregate").json()["groups"]
    twelve = next(g for g in groups if g["list"] == "12")
    assert twelve["items"] == [] and [g["name"] for g in twelve["groups"]] == ["widgets"]
    ok, read = call(setup.manager, "task_manager_tasks_list", {"aggregate": True})
    assert ok and [g["name"] for g in next(x for x in read["groups"] if x["list"] == "12")["groups"]] == ["widgets"]
