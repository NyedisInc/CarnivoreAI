
from __future__ import annotations


from src.cplugs.huddle import your_items
from src.cplugs.huddle.rules import CLAUDE, JOE
from tests.python.cplugs.huddle.test_task_manager_mcp import call, huddle_store, manager  # noqa: F401


def hold(manager, text: str, state: str, by: str = "ses_1") -> int:  # noqa: F811
    store = huddle_store(manager)
    item = store.add("12", text, actor=JOE)["id"]
    if state == "working":
        store.mark_working(item, by)
    else:
        store.update(item, actor=CLAUDE, state=state)
    return item


def test_the_field_lists_working_and_waiting_install(manager):
    working = hold(manager, "build the thing", "working")
    waiting = hold(manager, "install the thing", "waiting")
    ok, out = call(manager, "task_manager_tasks_list", {"list": "mine"})
    assert ok
    held = {i["id"]: i for i in out["your_items"]}
    assert held[working]["state"] == "working" and held[waiting]["state"] == "waiting"
    assert set(held[working]) == {"id", "title", "state", "age_min"} and held[working]["age_min"] == 0
    assert "your_items_more" not in out


def test_absent_when_the_caller_holds_nothing(manager):
    huddle_store(manager).add("12", "plain open item", actor=JOE)
    ok, out = call(manager, "task_manager_tasks_list", {"list": "mine"})
    assert ok and "your_items" not in out and "your_items_more" not in out


def test_another_sessions_working_claim_never_appears(manager):
    hold(manager, "theirs", "working", by="ses_other")
    ok, out = call(manager, "task_manager_tasks_list", {"list": "mine"})
    assert ok and "your_items" not in out


def test_a_waiting_install_item_on_another_project_list_never_appears(manager):
    item = huddle_store(manager).add("99", "other project", actor=JOE)["id"]
    huddle_store(manager).update(item, actor=CLAUDE, state="waiting")
    ok, out = call(manager, "task_manager_tasks_list", {"list": "mine"})
    assert ok and "your_items" not in out


def test_the_cap_lists_five_and_counts_the_rest(manager):
    for n in range(7):
        hold(manager, f"item {n}", "working")
    ok, out = call(manager, "task_manager_tasks_list", {"list": "mine"})
    assert ok and len(out["your_items"]) == your_items.CAP == 5 and out["your_items_more"] == 2


def test_titles_are_truncated_and_redacted(manager):
    hold(manager, "x" * 200, "working")
    ok, out = call(manager, "task_manager_tasks_list", {"list": "mine"})
    assert ok and len(out["your_items"][0]["title"]) == 60


def test_lean_write_answers_and_batch_carry_it(manager):
    hold(manager, "owed", "working")
    ok, out = call(manager, "task_manager_add", {"list": "mine", "text": "new"}, raw=True)
    assert ok and out["your_items"][0]["state"] == "working"
    ok, out = call(manager, "task_manager_batch_run", {"list_id": "mine", "ops": [{"op": "add", "text": "b"}]})
    assert ok and out["your_items"]
