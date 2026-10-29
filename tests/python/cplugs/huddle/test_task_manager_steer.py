
from __future__ import annotations

import pytest

from src.cplugs.huddle import mcp, steer
from tests.python.cplugs.huddle.test_task_manager_mcp import call, huddle_store, manager  # noqa: F401


@pytest.mark.parametrize("text", [
    "done with the build.\nshould I ship it?",
    "ship it?  \n\n",
    "**ready to ship?**",
    "options:\n1. keep the cache?\n2. drop it?\nthanks",
])
def test_question_like_text_is_detected(text):
    assert steer.reads_like_question(text)


@pytest.mark.parametrize("text", [
    "did you mean x? no, it is y.",
    "fixed. what next is up to you.",
    "1. built the thing?\nonly one numbered question, then a statement.",
    "",
    None,
])
def test_statements_and_one_midtext_question_mark_are_not_questions(text):
    assert not steer.reads_like_question(text)


@pytest.fixture
def item(manager):
    return huddle_store(manager).add("12", "work", actor="joe")["id"]


@pytest.mark.parametrize("kind", ["info", "answer"])
def test_reply_that_reads_like_a_question_is_refused(manager, item, kind):
    args = {"item": item, "text": "ready?", "kind": kind}
    if kind == "answer":
        args["quote_text"] = "his words"
    ok, out = call(manager, "task_manager_reply", args)
    assert not ok and "questions go in task_manager_ask with `questions`; an info is never answered" in out
    assert huddle_store(manager).item(item)["thread"] == []


def test_override_lets_it_post_and_a_look_that_asks_is_refused(manager, item):
    ok, out = call(manager, "task_manager_reply", {"item": item, "text": "ready?", "kind": "info", "not_a_question": True})
    assert ok and out["kind"] == "info"
    ok, out = call(manager, "task_manager_reply", {"item": item, "text": "ok to push?", "kind": "attention", "action": "push"})
    assert not ok and "task_manager_update" in out


def test_an_omitted_kind_on_a_working_item_is_an_info_and_refused(manager, item):
    call(manager, "task_manager_update", {"item": item, "state": "working"})
    ok, out = call(manager, "task_manager_reply", {"item": item, "text": "which one?"})
    assert not ok and "task_manager_ask" in out


def test_plain_ask_with_two_question_marks_is_refused_unless_questions(manager, item):
    ok, out = call(manager, "task_manager_ask", {"item": item, "text": "a? b?"})
    assert not ok and "questions" in out
    ok, out = call(manager, "task_manager_ask", {"item": item, "text": "just one?"})
    assert ok and out["reaches_owner"] is True
    ok, out = call(manager, "task_manager_ask", {"item": item, "questions": ["a?", "b?"]})
    assert ok and out["reaches_owner"] is True and out["reaches_owner_reason"]


def test_reaches_owner_for_each_write(manager, item):
    ok, out = call(manager, "task_manager_update", {"item": item, "state": "working"})
    assert ok and out["reaches_owner"] is False and "working and folded" in out["reaches_owner_reason"]
    ok, out = call(manager, "task_manager_reply", {"item": item, "text": "progress", "kind": "info"})
    assert ok and out["reaches_owner"] is False and out["reaches_owner_reason"]
    ok, out = call(manager, "task_manager_reply", {"item": item, "text": "look", "kind": "attention", "action": "read"})
    assert ok and out["reaches_owner"] is False and out["kind"] == "info"
    ok, out = call(manager, "task_manager_reply", {"item": item, "text": "look", "kind": "info", "notify": True})
    assert ok and out["reaches_owner"] is False and "notify" in out["reaches_owner_reason"]
    ok, out = call(manager, "task_manager_reply", {"item": item, "text": "look", "kind": "attention", "action": "tick"})
    assert not ok
    ok, out = call(manager, "task_manager_move", {"item": item, "list": "all"})
    assert ok and out["reaches_owner"] is False
    ok, out = call(manager, "task_manager_update", {"item": item, "state": "review"})
    assert ok and out["reaches_owner"] is True and out["id"] == item
    ok, out = call(manager, "task_manager_add", {"list": "12", "text": "new"})
    assert ok and out["reaches_owner"] is False
    ok, out = call(manager, "task_manager_add", {"list": "12", "text": "why?", "kind": "question"})
    assert ok and out["reaches_owner"] is True


def test_full_answers_carry_the_fields_too(manager, item):
    ok, out = call(manager, "task_manager_reply", {"item": item, "text": "fyi", "kind": "info", "lean": False})
    assert ok and out["reaches_owner"] is False and out["item"]["id"] == item


def test_batch_ops_refuse_and_report_per_op(manager, item):
    ops = [{"op": "reply", "item_id": item, "text": "need a call?", "kind": "info"},
           {"op": "reply", "item_id": item, "text": "need a call?", "kind": "info", "not_a_question": True},
           {"op": "update", "item_id": item, "state": "review"},
           {"op": "ask", "item_id": item, "text": "a? b?"},
           {"op": "ask", "item_id": item, "questions": ["a?", "b?"]},
           {"op": "move", "item_id": item, "list": "all"}]
    ok, body = call(manager, "task_manager_batch_run", {"list_id": "12", "ops": ops})
    assert ok
    r = body["results"]
    assert [x["ok"] for x in r] == [False, True, True, False, True, True]
    assert "task_manager_ask" in r[0]["error"] and "questions" in r[3]["error"]
    assert [x["reaches_owner"] for x in r if x["ok"]] == [False, True, True, False]


def test_descriptions_carry_the_line_within_budget():
    for name in ("task_manager_reply", "task_manager_update", "task_manager_ask"):
        desc = mcp.TOOLS[name].description
        assert "reaches the owner" in desc and len(desc) <= 400


def test_answer_to_the_owner_on_a_working_item_reaches_him_until_read(manager, item):
    store = huddle_store(manager)
    asked = store.post(item, "why is this slow?", actor="joe")["message"]["id"]
    call(manager, "task_manager_update", {"item": item, "state": "working"})
    ok, out = call(manager, "task_manager_reply", {"item": item, "text": "the cache", "kind": "answer", "quote": asked})
    assert ok and out["reaches_owner"] is True
    row = store.item(item)
    assert row["status"] == "working" and row["needs_you"] is True and row["needs_action"] == "read"
    ok, info = call(manager, "task_manager_reply", {"item": item, "text": "fyi", "kind": "info"})
    assert ok and info["reaches_owner"] is False
    assert store.item(item)["needs_action"] == "read"
    store.mark_seen(item, out["message_id"])
    store.mark_seen(item, info["message_id"])
    row = store.item(item)
    assert row["needs_you"] is False and row["status"] == "working"
