
from __future__ import annotations

from dataclasses import replace

from src.cplugs.host import runtime, state as owner_state
from src.cplugs.huddle import lifecycle
from src.cplugs.huddle.rules import JOE
from src.cplugs.huddle.store import TaskManagerStore
from tests.python.cplugs.huddle.test_task_manager_mcp import call, manager  # noqa: F401


def set_view(manager, view: str) -> None:
    host = runtime.host_for(manager.app)
    d = runtime.find("huddle")
    owner_state.update(host.state_dir, d.manifest, None, lambda st: replace(st, settings={**st.settings, "view": view}))


def store(manager, view: str) -> TaskManagerStore:
    return TaskManagerStore(runtime.host_for(manager.app).storage("huddle"), notify=lambda key: None, view=view)


def test_the_view_setting_defaults_to_status():
    d = runtime.find("huddle")
    assert d.manifest.settings_schema["fields"]["view"]["default"] == lifecycle.VIEW_STATUS
    assert d.manifest.settings_schema["fields"]["view"]["options"] == ["status", "area"]


def test_section_files_the_ticked_state_under_done_and_ranks_top_to_bottom():
    assert [lifecycle.section_of(s) for s in lifecycle.STATUSES] == [
        "done", "question", "waiting_to_send", "review", "waiting", "working", "scheduled", "open", "todo"]
    assert sorted(lifecycle.SECTIONS, key=lifecycle.section_rank) == [
        "question", "review", "waiting", "working", "waiting_to_send", "scheduled", "open", "todo", "done"]


def test_status_view_numbers_count_through_the_sections_and_area_view_through_the_list(manager):
    area = store(manager, lifecycle.VIEW_AREA)
    status = store(manager, lifecycle.VIEW_STATUS)
    ok, a = call(manager, "task_manager_add", {"list": "all", "text": "open one"})
    ok, b = call(manager, "task_manager_add", {"list": "all", "text": "done one"})
    call(manager, "task_manager_update", {"item": b["id"], "state": "review"})
    ok, c = call(manager, "task_manager_add", {"list": "all", "text": "ask one", "kind": "question"})
    by_area = {i["id"]: (i["number"], i["section"]) for i in area.list_items("all")["items"]}
    assert by_area == {c["id"]: (1, "question"), b["id"]: (2, "review"), a["id"]: (3, "open")}
    by_status = {i["id"]: i["number"] for i in status.list_items("all")["items"]}
    assert by_status == {c["id"]: 1, b["id"]: 2, a["id"]: 3}
    assert status.item(a["id"])["number"] == 3 and area.item(a["id"])["number"] == 3
    ok, d = call(manager, "task_manager_add", {"list": "all", "text": "grouped open", "group": "widgets"})
    ok, e = call(manager, "task_manager_add", {"list": "all", "text": "grouped ask", "group": "widgets", "kind": "question"})
    by_area = {i["id"]: i["number"] for i in area.list_items("all")["items"]}
    assert by_area == {c["id"]: 1, b["id"]: 2, a["id"]: 3, e["id"]: 4, d["id"]: 5}
    by_status = {i["id"]: i["number"] for i in status.list_items("all")["items"]}
    assert by_status == {c["id"]: 1, e["id"]: 2, b["id"]: 3, a["id"]: 4, d["id"]: 5}


def test_an_mcp_read_answers_the_numbers_he_sees_after_the_read_moved_rows(manager):
    set_view(manager, lifecycle.VIEW_STATUS)
    ok, claude_item = call(manager, "task_manager_add", {"list": "all", "text": "claude's"})
    call(manager, "task_manager_update", {"item": claude_item["id"], "state": "review"})
    joe_item = store(manager, lifecycle.VIEW_STATUS).add("all", "joe's", actor=JOE)
    before = {i["id"]: i["number"] for i in store(manager, lifecycle.VIEW_STATUS).list_items("all")["items"]}
    assert before == {claude_item["id"]: 1, joe_item["id"]: 2}
    told = store(manager, lifecycle.VIEW_STATUS)
    told.record_send(["all"], told.current_cursor())
    ok, listed = call(manager, "task_manager_tasks_list", {"list": "all"})
    answered = {i["id"]: (i["number"], i["section"]) for i in listed["items"]}
    screen = {i["id"]: (i["number"], i["section"]) for i in store(manager, lifecycle.VIEW_STATUS).list_items("all")["items"]}
    assert answered == screen == {claude_item["id"]: (1, "review"), joe_item["id"]: (2, "open")}


def test_area_view_setting_numbers_down_the_groups_in_mcp(manager):
    set_view(manager, lifecycle.VIEW_AREA)
    ok, a = call(manager, "task_manager_add", {"list": "all", "text": "first", "group": "widgets"})
    ok, b = call(manager, "task_manager_add", {"list": "all", "text": "second", "kind": "question"})
    ok, listed = call(manager, "task_manager_tasks_list", {"list": "all"})
    assert {i["id"]: i["number"] for i in listed["items"]} == {b["id"]: 1, a["id"]: 2}
    set_view(manager, lifecycle.VIEW_STATUS)
    call(manager, "task_manager_move", {"item": b["id"], "group": "widgets"})
    ok, listed = call(manager, "task_manager_tasks_list", {"list": "all"})
    assert {i["id"]: i["number"] for i in listed["items"]} == {b["id"]: 1, a["id"]: 2}
