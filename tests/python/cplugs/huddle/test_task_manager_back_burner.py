
from __future__ import annotations

from src.cplugs.huddle import lifecycle
from src.cplugs.huddle.rules import CLAUDE, JOE
from tests.python.cplugs.huddle.test_task_manager_mcp import call, huddle_store, manager  # noqa: F401


def test_the_section_sits_just_above_done_and_the_status_is_its_own():
    assert lifecycle.SECTIONS[-2:] == ("todo", "done")
    assert lifecycle.section_of("todo") == "todo"
    assert lifecycle.section_rank("todo") == lifecycle.section_rank("done") - 1


def test_claude_sets_it_over_mcp_and_open_takes_it_off(manager):
    ok, item = call(manager, "task_manager_add", {"list": "all", "text": "later"})
    ok, item = call(manager, "task_manager_update", {"item": item["id"], "state": "todo"})
    assert ok and item["state"] == "todo" and item["status"] == "todo"
    ok, listed = call(manager, "task_manager_tasks_list", {"list": "all"})
    assert [(i["status"], i["section"]) for i in listed["items"]] == [("todo", "todo")]
    ok, item = call(manager, "task_manager_update", {"item": item["id"], "state": "open"})
    assert item["state"] == "open" and item["status"] == "open"


def test_huddle_batch_sets_it(manager):
    store = huddle_store(manager)
    item = store.add("12", "later", actor=JOE)
    ok, body = call(manager, "task_manager_batch_run", {"list_id": "mine", "ops": [{"op": "update", "item_id": item["id"], "state": "todo"}]})
    assert ok and body["applied"] == 1 and store.item(item["id"])["status"] == "todo"


def test_joe_sets_it_and_takes_it_off(manager):
    store = huddle_store(manager)
    item = store.add("all", "later", actor=JOE)
    assert store.update(item["id"], actor=JOE, state="todo")["status"] == "todo"
    assert store.update(item["id"], actor=JOE, state="open")["status"] in ("open", "waiting_to_send")
    assert store.item(item["id"])["state"] == "open"


def test_it_ends_a_working_claim(manager):
    ok, item = call(manager, "task_manager_add", {"list": "all", "text": "later"})
    ok, item = call(manager, "task_manager_update", {"item": item["id"], "state": "working"})
    assert item["status"] == "working"
    ok, item = call(manager, "task_manager_update", {"item": item["id"], "state": "todo"})
    assert item["status"] == "todo"


def test_it_counts_in_neither_the_incomplete_number_nor_the_tell_count(manager):
    store = huddle_store(manager)
    keep = store.add("all", "today", actor=JOE)
    parked = store.add("all", "later", actor=JOE)
    before = store.summary()["lists"]["all"]
    assert before["incomplete"] == 2 and before["waiting_to_send"] == 2
    store.update(parked["id"], actor=JOE, state="todo")
    after = store.summary()["lists"]["all"]
    assert after["incomplete"] == 1 and after["waiting_to_send"] == 1
    assert store.item(keep["id"])["status"] == "waiting_to_send"


def test_a_joe_reply_does_not_pull_it_out_but_shows_as_a_note_waiting(manager):
    store = huddle_store(manager)
    ok, item = call(manager, "task_manager_add", {"list": "all", "text": "later"})
    call(manager, "task_manager_update", {"item": item["id"], "state": "todo"})
    quiet = store.item(item["id"])
    assert quiet["note_waiting"] is False
    posted = store.post(item["id"], "remember the edge case", actor=JOE, kind="reply")["item"]
    assert posted["state"] == "todo" and posted["status"] == "todo" and posted["note_waiting"] is True
    summary = store.summary()["lists"]["all"]
    assert summary["waiting_to_send"] == 0 and summary["incomplete"] == 0
    call(manager, "task_manager_tasks_list", {"list": "all"})
    assert store.item(item["id"])["note_waiting"] is False


def test_the_mcp_text_says_claude_leaves_back_burner_items_alone(manager):
    from src.core.mcp import tools
    defs = {d["name"]: d for d in tools.tool_definitions()}
    for tool in ("task_manager_tasks_list", "task_manager_update"):
        text = defs[tool]["description"]
        assert "todo" in text and "unless the owner asks" in text
    assert "todo" in defs["task_manager_update"]["inputSchema"]["properties"]["state"]["enum"]
