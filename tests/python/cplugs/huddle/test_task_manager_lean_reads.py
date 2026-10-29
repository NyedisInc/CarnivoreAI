
from __future__ import annotations

import json

import pytest
import structlog

from src.core.mcp import tools
from src.cplugs.huddle import lean_read
from tests.python.cplugs.huddle.test_task_manager_mcp import CALLER, call, huddle_store, manager  # noqa: F401

SUMMARY_KEYS = {"id", "number", "title", "status", "section", "unread"}
FORM = [{"id": "pick", "type": "single", "prompt": "Which one?", "options": [{"label": "a"}, {"label": "b"}]}]


def _add(manager, n=3, text="item", list_key="12", **extra):
    store = huddle_store(manager)
    return [store.add(list_key, f"{text} {i}", actor="joe", **extra)["id"] for i in range(n)]


def test_the_default_is_summary_rows_with_no_thread_or_approved_item(manager):
    a, b, c = _add(manager)
    store = huddle_store(manager)
    store.post(a, "an info", actor="claude")
    store.update(c, actor="joe", approve=True)
    ok, listed = call(manager, "task_manager_tasks_list", {"list": "12"})
    assert ok and [i["id"] for i in listed["items"]] == [a, b]
    assert listed["approved_hidden"] == 1 and listed["total"] == 2
    for row in listed["items"]:
        assert SUMMARY_KEYS <= set(row) and not {"text", "note", "thread", "review_description"} & set(row)
    assert listed["items"][0]["title"] == "item 0"


def test_a_title_wins_over_the_text_lead_and_a_long_lead_is_cut(manager):
    store = huddle_store(manager)
    titled = store.add("12", "body", actor="joe", title="short title")["id"]
    long_one = store.add("12", "x" * 300, actor="joe")["id"]
    ok, listed = call(manager, "task_manager_tasks_list", {"list": "12"})
    rows = {r["id"]: r for r in listed["items"]}
    assert rows[titled]["title"] == "short title"
    assert len(rows[long_one]["title"]) == lean_read.LEAD_MAX


def test_summary_rows_carry_group_and_action_only_when_set(manager):
    (a,) = _add(manager, 1, list_key="all")
    call(manager, "task_manager_update", {"item": a, "state": "review", "review_action": "push"})
    ok, grouped = call(manager, "task_manager_move", {"item": a, "group": "build"})
    ok, listed = call(manager, "task_manager_tasks_list", {"list": "all"})
    row = listed["items"][0]
    assert row["review_action"] == "push" and row["group"] == grouped["group"]
    plain = call(manager, "task_manager_add", {"list": "all", "text": "plain"}, raw=True)[1]["item_id"]
    row = next(r for r in call(manager, "task_manager_tasks_list", {"list": "all"})[1]["items"] if r["id"] == plain)
    assert not {"group", "needs_action", "forked_from", "review_action"} & set(row)


def test_fields_opt_in_to_text_note_thread_and_review(manager):
    a, b = _add(manager, 2)
    huddle_store(manager).post(a, "an info", actor="claude")
    call(manager, "task_manager_update", {"item": a, "review_where": "the tab"})
    ok, listed = call(manager, "task_manager_tasks_list", {"list": "12", "fields": ["text", "thread", "review"]})
    first = next(r for r in listed["items"] if r["id"] == a)
    assert first["text"] == "item 0" and first["thread"][0]["text"] == "an info" and first["review_where"] == "the tab"
    assert "note" not in first
    ok, only = call(manager, "task_manager_tasks_list", {"list": "12", "fields": "note,kind"})
    assert ok and "text" not in only["items"][0] and "thread" not in only["items"][0]
    ok, full = call(manager, "task_manager_tasks_list", {"list": "12", "fields": "full"})
    assert {"text", "note", "thread", "list", "created_by"} <= set(full["items"][0])
    ok, legacy = call(manager, "task_manager_tasks_list", {"list": "12", "include_thread": True})
    assert "thread" in legacy["items"][0]


def test_an_unknown_field_is_refused(manager):
    ok, text = call(manager, "task_manager_tasks_list", {"list": "12", "fields": ["nope"]})
    assert not ok and "unknown field" in text


def test_include_approved_brings_the_done_section_back(manager):
    a, b = _add(manager, 2)
    huddle_store(manager).update(b, actor="joe", approve=True)
    ok, listed = call(manager, "task_manager_tasks_list", {"list": "12", "include_approved": True})
    assert [i["id"] for i in listed["items"]] == [a, b] and "approved_hidden" not in listed


def test_item_reads_one_item_in_full_with_its_thread(manager):
    a, b = _add(manager, 2)
    huddle_store(manager).post(b, "an info", actor="claude")
    ok, one = call(manager, "task_manager_tasks_list", {"item": b})
    assert ok and one["item"]["id"] == b and one["item"]["text"] == "item 1" and one["item"]["thread"][0]["text"] == "an info"
    ok, text = call(manager, "task_manager_tasks_list", {"item": 99999})
    assert not ok and "not_found" in text


def test_limit_and_cursor_page_in_screen_order(manager):
    ids = _add(manager, 5)
    ok, first = call(manager, "task_manager_tasks_list", {"list": "12", "limit": 2})
    assert [i["id"] for i in first["items"]] == ids[:2] and first["next_cursor"] == "2" and first["total"] == 5
    ok, second = call(manager, "task_manager_tasks_list", {"list": "12", "limit": 2, "cursor": first["next_cursor"]})
    assert [i["id"] for i in second["items"]] == ids[2:4]
    ok, last = call(manager, "task_manager_tasks_list", {"list": "12", "limit": 2, "cursor": second["next_cursor"]})
    assert [i["id"] for i in last["items"]] == ids[4:] and "next_cursor" not in last
    ok, text = call(manager, "task_manager_tasks_list", {"list": "12", "limit": 0})
    assert not ok and "limit" in text


def test_aggregate_is_lean_too(manager):
    _add(manager, 2, list_key="12")
    _add(manager, 1, list_key="all")
    ok, agg = call(manager, "task_manager_tasks_list", {"aggregate": True})
    rows = [i for g in agg["groups"] for i in g["items"]]
    assert ok and len(rows) == 3 and all("thread" not in r and "text" not in r for r in rows)
    ok, page = call(manager, "task_manager_tasks_list", {"aggregate": True, "limit": 1})
    assert len([i for g in page["groups"] for i in g["items"]]) == 1 and page["next_cursor"] == "1"


def test_a_read_of_the_list_still_reads_the_hidden_approved_items(manager):
    (a,) = _add(manager, 1, list_key="all")
    store = huddle_store(manager)
    store.update(a, actor="joe", approve=True)
    assert store.item(a)["status"] == "waiting_to_send"
    call(manager, "task_manager_tasks_list", {"list": "all"})
    assert store.item(a)["status"] == "done"



def test_a_bulk_renumber_that_only_moves_derived_fields_sends_the_lean_shape(manager):
    ids = _add(manager, 4)
    ok, start = call(manager, "task_manager_tasks_list", {"list": "12", "fields": "full"})
    store = huddle_store(manager)
    store.reorder("12", list(reversed(ids)), actor="joe", expected_revision=store.list_items("12")["revision"])
    ok, changed = call(manager, "task_manager_changes", {"since": start["cursor"], "list": "12"})
    assert {i["id"] for i in changed["items"]} == set(ids)
    assert all(set(i) == {"id", "status", "section", "revision"} for i in changed["items"])


def test_a_pane_that_read_only_summaries_holds_the_revision_too(manager):
    a, b = _add(manager, 2)
    ok, start = call(manager, "task_manager_tasks_list", {"list": "12"})
    huddle_store(manager).post(b, "owner hi", actor="joe")
    ok, changed = call(manager, "task_manager_changes", {"since": start["cursor"], "list": "12"})
    assert [set(i) for i in changed["items"]] == [{"id", "status", "section", "revision"}]


def test_a_revision_bump_or_a_pane_that_never_held_it_gets_the_item_whole(manager):
    (a,) = _add(manager, 1)
    call(manager, "task_manager_tasks_list", {"list": "12"})
    cursor = call(manager, "task_manager_tasks_list", {"list": "12"})[1]["cursor"]
    huddle_store(manager).update(a, actor="joe", text="reworded")
    ok, changed = call(manager, "task_manager_changes", {"since": cursor, "list": "12"})
    assert changed["items"][0]["text"] == "reworded"


def test_changes_leave_out_the_callers_own_posts_unless_asked_and_keep_the_owners(manager):
    (a,) = _add(manager, 1)
    call(manager, "task_manager_reply", {"item": a, "text": "my own note", "kind": "info"})
    huddle_store(manager).post(a, "owner says", actor="joe")
    ok, changed = call(manager, "task_manager_changes", {"since": 0, "list": "12"})
    assert [m["text"] for m in changed["messages"]] == ["owner says"] and changed["omitted_own"] == 1
    ok, mine = call(manager, "task_manager_changes", {"since": 0, "list": "12", "include_mine": True})
    assert [m["text"] for m in mine["messages"]] == ["my own note", "owner says"] and "omitted_own" not in mine
    sibling = type(CALLER)("ses_2", "cloude_b", "ses_2")
    ok, other = call(manager, "task_manager_changes", {"since": 0, "list": "12"}, caller=sibling)
    assert [m["text"] for m in other["messages"]] == ["my own note", "owner says"]



def test_a_form_message_sends_the_structure_and_only_a_text_lead(manager):
    (a,) = _add(manager, 1)
    ok, asked = call(manager, "task_manager_ask", {"item": a, "context": "background line\nmore background", "questions": FORM})
    ok, body = call(manager, "task_manager_tasks_list", {"item": a})
    message = body["item"]["thread"][0]
    assert message["form"][0]["id"] == "pick" and message["text"] == "background line"
    assert len(message["text"]) <= lean_read.LEAD_MAX and "Which one?" not in message["text"]


def test_an_answer_message_sends_its_answers_and_one_text_line_per_question():
    from src.cplugs.huddle import mcp
    message = {"id": 9, "author": "joe", "kind": "reply", "text": "answers to 1 question:\n1. Which one? a", "answered": False,
               "answers_to": 4,
               "answers": {"pick": {"choice": "o1", "label": "a", "prompt": "Which one?"}, "why": {"text": "because", "prompt": "Why?"},
                           "_extra": {"text": "ship it"}}}
    out = mcp._thread_message(message)
    assert out["answers"] == message["answers"]
    assert out["text"] == "answers to 1 question:\n1. Which one?: a\n2. Why?: because\nanything else: ship it"


def test_a_plain_message_keeps_its_whole_text(manager):
    from src.cplugs.huddle import mcp
    out = mcp._thread_message({"id": 1, "author": "joe", "kind": "reply", "text": "line one\nline two", "answered": False})
    assert out["text"] == "line one\nline two"



def test_every_huddle_tool_description_is_at_most_400_characters():
    huddle = {d["name"]: d["description"] for d in tools.tool_definitions() if d["name"].startswith("huddle_")}
    assert len(huddle) >= 14
    assert {n: len(t) for n, t in huddle.items() if len(t) > 400} == {}


def test_the_descriptions_keep_the_behavior_rules():
    defs = {d["name"]: d["description"] for d in tools.tool_definitions()}
    assert "todo" in defs["task_manager_tasks_list"] and "unless the owner asks" in defs["task_manager_tasks_list"]
    assert "Only the owner approves" in defs["task_manager_update"]
    assert "blocked" in defs["task_manager_ask"] and "task_manager_reply" in defs["task_manager_ask"]
    assert "task_manager_ask" in defs["task_manager_reply"] and "answer" in defs["task_manager_reply"] and "info" in defs["task_manager_reply"]


def test_every_tool_result_logs_its_size_on_the_shared_dispatch_path(manager):
    with structlog.testing.capture_logs() as logs:
        ok, listed = call(manager, "task_manager_tasks_list", {"list": "12"})
        result = json.dumps(listed)  # noqa: F841
    entries = [e for e in logs if e["event"] == "mcp.tool_result"]
    assert entries and entries[-1]["tool"] == "task_manager_tasks_list" and entries[-1]["chars"] > 0 and entries[-1]["is_error"] is False
