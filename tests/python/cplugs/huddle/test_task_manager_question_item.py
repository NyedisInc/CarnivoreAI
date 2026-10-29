from __future__ import annotations

from src.cplugs.huddle import service
from tests.python.cplugs.huddle.test_task_manager_mcp import call, huddle_store, manager  # noqa: F401


def _quiet(monkeypatch):
    monkeypatch.setattr(service, "surface_question", lambda ctx, sid, item, message: True)


def test_adding_a_question_item_files_a_real_question_post(manager, monkeypatch):
    _quiet(monkeypatch)
    ok, added = call(manager, "task_manager_add", {"list": "all", "text": "review area rework?", "kind": "question"})
    assert ok
    item = huddle_store(manager).item(added["id"])
    questions = [m for m in item["thread"] if m["kind"] == "question"]
    assert len(questions) == 1 and questions[0]["text"] == "review area rework?" and not questions[0]["answered"]
    assert item["status"] == "question"


def test_a_plain_add_files_no_post(manager, monkeypatch):
    _quiet(monkeypatch)
    ok, added = call(manager, "task_manager_add", {"list": "all", "text": "just a task", "kind": "info"})
    assert ok and huddle_store(manager).item(added["id"])["thread"] == []


def test_an_old_item_level_question_is_ended_by_mark_answered(manager):
    store = huddle_store(manager)
    item = store.add("all", "which one?", actor="claude", kind="question")["id"]
    assert store.item(item)["status"] == "question" and store.item(item)["thread"] == []
    after = store.mark_answered(item, actor="joe")
    assert after["status"] != "question"
