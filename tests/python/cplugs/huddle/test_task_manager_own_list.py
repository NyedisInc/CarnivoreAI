
from __future__ import annotations

import pytest

from src.core.mcp.caller import AgentCaller
from src.cplugs.huddle import service
from tests.python.cplugs.huddle.test_task_manager_mcp import CALLER, call, huddle_store, manager  # noqa: F401

REFUSAL = ("item {item} is on the Blog list, not your project Carnivore. Write to your own list (list: mine). "
           "If this really belongs on Blog's list, repeat the call with cross_project: true.")


@pytest.fixture(autouse=True)
def two_projects(monkeypatch):
    monkeypatch.setattr(service, "project_names", lambda ctx: {"12": "Carnivore", "7": "Blog"})


def blog_item(manager) -> int:
    return huddle_store(manager).add("7", "blog work", actor="joe")["id"]


def test_same_project_is_allowed_and_carries_no_marker(manager):
    ok, item = call(manager, "task_manager_add", {"list": "12", "text": "mine"})
    assert ok and item["list"] == "12" and "cross_project" not in item and "warning" not in item
    ok, item = call(manager, "task_manager_add", {"list": "mine", "text": "also mine"})
    assert ok and item["list"] == "12"


def test_another_project_is_refused_with_both_names_and_nothing_is_written(manager):
    item = blog_item(manager)
    ok, text = call(manager, "task_manager_reply", {"item": item, "text": "hi", "kind": "info"})
    assert not ok and text == REFUSAL.format(item=item)
    ok, text = call(manager, "task_manager_add", {"list": "7", "text": "x"})
    assert not ok and "this write is on the Blog list, not your project Carnivore" in text
    assert [m for m in huddle_store(manager).item(item)["thread"]] == []
    assert [i["text"] for i in huddle_store(manager).list_items("7")["items"]] == ["blog work"]


@pytest.mark.parametrize("tool,extra", [
    ("task_manager_update", {"state": "working"}), ("task_manager_ask", {"text": "which one?"}), ("task_manager_answered_set", {}),
    ("task_manager_progress_set", {"phase": "running"}), ("task_manager_move", {"list": "12"}),
    ("task_manager_fork", {}), ("huddle_focus", {"list": "7", "items": []}),
])
def test_every_write_tool_is_guarded(manager, tool, extra):
    item = blog_item(manager)
    args = dict(extra) if tool == "huddle_focus" else {"item": item, **extra}
    ok, text = call(manager, tool, args)
    assert not ok and "not your project Carnivore" in text and "cross_project: true" in text, (tool, text)


def test_groups_are_guarded(manager):
    ok, text = call(manager, "task_manager_group_create", {"list": "7", "name": "auth"})
    assert not ok and "not your project Carnivore" in text
    ok, group = call(manager, "task_manager_group_create", {"list": "7", "name": "auth", "cross_project": True})
    assert ok and group["cross_project"] == {"from": "Carnivore", "to": "Blog"}
    ok, text = call(manager, "task_manager_group_update", {"group": group["id"], "name": "login"})
    assert not ok and "group %d is on the Blog list" % group["id"] in text
    ok, renamed = call(manager, "task_manager_group_update", {"group": group["id"], "name": "login", "cross_project": True})
    assert ok and renamed["name"] == "login" and renamed["cross_project"]["to"] == "Blog"


def test_moving_an_item_off_another_project_is_guarded_even_into_your_own(manager):
    item = blog_item(manager)
    ok, text = call(manager, "task_manager_move", {"item": item, "list": "mine"})
    assert not ok and text == REFUSAL.format(item=item)


def test_cross_project_true_is_allowed_answers_the_crossing_and_is_recorded(manager):
    item = blog_item(manager)
    ok, out = call(manager, "task_manager_reply", {"item": item, "text": "hi", "kind": "info", "cross_project": True})
    assert ok and out["item"]["id"] == item and out["cross_project"] == {"from": "Carnivore", "to": "Blog"}
    thread = huddle_store(manager).item(item)["thread"]
    assert [m["text"] for m in thread] == ["hi", "written from another project: Carnivore"] or \
        sorted(m["text"] for m in thread) == sorted(["hi", "written from another project: Carnivore"])
    ok, lean = call(manager, "task_manager_update", {"item": item, "state": "working", "cross_project": True, "lean": True}, raw=True)
    assert ok and lean["cross_project"] == {"from": "Carnivore", "to": "Blog"}


def test_cross_project_add_records_on_the_new_item(manager):
    ok, item = call(manager, "task_manager_add", {"list": "7", "text": "for blog", "cross_project": True})
    assert ok and item["list"] == "7" and item["cross_project"]["to"] == "Blog"
    assert [m["text"] for m in huddle_store(manager).item(item["id"])["thread"]] == ["written from another project: Carnivore"]


def test_a_caller_with_no_session_is_not_guarded(manager):
    item = blog_item(manager)
    token = AgentCaller("mcp-token:1", "mcp-token:1", "mcp-token:1", "tok", "write")
    ok, out = call(manager, "task_manager_reply", {"item": item, "text": "hi", "kind": "info"}, caller=token)
    assert ok and "cross_project" not in out and "warning" not in out


def test_a_session_with_no_project_is_allowed_with_a_warning(manager):
    item = blog_item(manager)
    stranger = AgentCaller("ses_9", "cloude_z", "ses_9")
    ok, out = call(manager, "task_manager_reply", {"item": item, "text": "hi", "kind": "info"}, caller=stranger)
    assert ok and out["warning"] == "could not tell your project"


def test_reads_and_the_shared_list_are_not_guarded(manager):
    blog_item(manager)
    assert call(manager, "task_manager_tasks_list", {"list": "7"})[0]
    assert call(manager, "task_manager_changes", {"since": 0})[0]
    ok, item = call(manager, "task_manager_add", {"list": "all", "text": "shared"})
    assert ok and "cross_project" not in item


def test_a_batch_refuses_only_the_crossing_op_and_reports_it_per_op(manager):
    other = blog_item(manager)
    mine = call(manager, "task_manager_add", {"list": "12", "text": "mine"})[1]["id"]
    ok, out = call(manager, "task_manager_batch_run", {"list_id": "12", "ops": [
        {"op": "update", "item_id": mine, "state": "working"},
        {"op": "add", "list": "7", "text": "to blog"},
        {"op": "add", "list": "7", "text": "to blog on purpose", "cross_project": True},
    ]})
    assert ok and out["applied"] == 2 and out["failed"] == 1
    assert out["results"][0]["ok"] and "cross_project" not in out["results"][0]
    assert not out["results"][1]["ok"] and "not your project Carnivore" in out["results"][1]["error"]
    assert out["results"][2]["ok"] and out["results"][2]["cross_project"] == {"from": "Carnivore", "to": "Blog"}
    ok, out = call(manager, "task_manager_batch_run", {"list_id": "7", "ops": [{"op": "update", "item_id": other, "state": "working"}]})
    assert ok and out["failed"] == 1 and "cross_project: true" in out["results"][0]["error"]
