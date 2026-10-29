
from __future__ import annotations

import json

from src.core.mcp import write_tools
from src.cplugs.huddle import batch, service
from src.core.mcp.caller import AgentCaller
from tests.python.cplugs.huddle.test_task_manager_mcp import CALLER, call, huddle_store, manager  # noqa: F401


def _items(manager, n=3, list_key="12"):
    store = huddle_store(manager)
    return [store.add(list_key, f"item {i}", actor="joe")["id"] for i in range(n)]


def test_mixed_ops_apply_and_answer_lean(manager):
    a, b, c = _items(manager)
    ops = [{"op": "update", "item_id": a, "state": "review", "review_description": "check it"},
           {"op": "reply", "item_id": b, "text": "found it", "kind": "info"},
           {"op": "mark_answered", "item_id": c},
           {"op": "move", "item_id": c, "list": "all"}]
    ok, body = call(manager, "task_manager_batch_run", {"list_id": "mine", "ops": ops})
    assert ok and body["applied"] == 4 and body["failed"] == 0
    for r in body["results"]:
        assert set(r) <= {"item_id", "ok", "state", "revision", "message_id", "reaches_owner", "reaches_owner_reason"} and r["ok"] is True
    assert [r["item_id"] for r in body["results"]] == [a, b, c, c]
    assert "message_id" in body["results"][1]
    store = huddle_store(manager)
    assert store.item(a)["state"] == "review"
    assert store.item(b)["thread"][0]["text"] == "found it"
    assert store.item(c)["list"] == "all"


def test_a_failing_op_keeps_earlier_ops_and_later_ops_still_run(manager):
    a, b, c = _items(manager)
    ops = [{"op": "update", "item_id": a, "state": "review"},
           {"op": "update", "item_id": b, "state": "done"},
           {"op": "update", "item_id": c, "state": "working"}]
    ok, body = call(manager, "task_manager_batch_run", {"list_id": "12", "ops": ops})
    assert ok and (body["applied"], body["failed"]) == (2, 1)
    assert [r["ok"] for r in body["results"]] == [True, False, True]
    assert body["results"][1]["item_id"] == b and "error" in body["results"][1]
    assert huddle_store(manager).item(a)["state"] == "review"
    assert huddle_store(manager).item(b)["state"] == "open"


def test_stop_on_error_skips_the_rest(manager):
    a, b, c = _items(manager)
    ops = [{"op": "update", "item_id": a, "state": "bogus"}, {"op": "update", "item_id": b, "state": "review"}]
    ok, body = call(manager, "task_manager_batch_run", {"list_id": "12", "ops": ops, "stop_on_error": True})
    assert ok and [r["ok"] for r in body["results"]] == [False, False]
    assert "skipped" in body["results"][1]["error"]
    assert huddle_store(manager).item(b)["state"] == "open"


def test_item_outside_the_list_and_bad_ops_are_refused_per_op(manager):
    (a,) = _items(manager, 1)
    (other,) = _items(manager, 1, "all")
    ops = [{"op": "update", "item_id": other, "state": "review"}, {"op": "nope", "item_id": a},
           {"op": "update", "item_id": "x"}, "junk"]
    ok, body = call(manager, "task_manager_batch_run", {"list_id": "12", "ops": ops})
    assert ok and body["failed"] == 4
    assert "not 12" in body["results"][0]["error"]
    assert huddle_store(manager).item(other)["state"] == "open"


def test_ops_are_capped_and_required(manager):
    ok, text = call(manager, "task_manager_batch_run", {"list_id": "12", "ops": []})
    assert not ok and "ops is required" in text
    ops = [{"op": "mark_answered", "item_id": 1}] * (batch.MAX_OPS + 1)
    ok, text = call(manager, "task_manager_batch_run", {"list_id": "12", "ops": ops})
    assert not ok and "at most" in text


def test_one_batch_is_one_approval_for_an_external_token(manager, monkeypatch):
    parked = []

    async def park(manager, caller, target_id, target_tmux, name, summary, shown, run, key):
        parked.append(name)
        return {"content": [{"type": "text", "text": json.dumps({"status": "pending", "id": "act_1"})}]}

    monkeypatch.setattr(write_tools, "park", park)
    a, b, c = _items(manager)
    external = AgentCaller("mcp-token:t", "mcp-token:t", "mcp-token:t", "tok", "write")
    ops = [{"op": "update", "item_id": i, "state": "review"} for i in (a, b, c)]
    ok, body = call(manager, "task_manager_batch_run", {"list_id": "12", "ops": ops}, caller=external)
    assert ok and body["status"] == "pending" and parked == ["task_manager_batch_run"]
    assert huddle_store(manager).item(a)["state"] == "open"


def test_single_write_tools_answer_lean_by_default_and_full_on_lean_false(manager):
    (a,) = _items(manager, 1)
    lean_keys = {"item_id", "ok", "state", "revision", "guide_rev", "reaches_owner", "reaches_owner_reason"}
    ok, added = call(manager, "task_manager_add", {"list": "12", "text": "new one"}, raw=True)
    assert ok and set(added) == lean_keys and added["state"] == "open"
    ok, full = call(manager, "task_manager_add", {"list": "12", "text": "new two", "lean": False}, raw=True)
    assert ok and full["text"] == "new two" and full["created_by"] == "claude"
    ok, lean = call(manager, "task_manager_reply", {"item": a, "text": "hello there", "kind": "info"}, raw=True)
    assert ok and set(lean) == lean_keys | {"message_id"}
    ok, full = call(manager, "task_manager_reply", {"item": a, "text": "again", "kind": "info", "lean": False}, raw=True)
    assert ok and "thread" in full["item"]
    ok, lean = call(manager, "task_manager_update", {"item": a, "state": "review"}, raw=True)
    assert ok and set(lean) == lean_keys and lean["state"] == "review"
    ok, full = call(manager, "task_manager_update", {"item": a, "state": "open", "lean": False}, raw=True)
    assert ok and "thread" in full and "text" in full
    ok, lean = call(manager, "task_manager_ask", {"item": a, "text": "which?"}, raw=True)
    assert ok and set(lean) == lean_keys | {"message_id"}
    ok, lean = call(manager, "task_manager_answered_set", {"item": a}, raw=True)
    assert ok and set(lean) == lean_keys
    ok, lean = call(manager, "task_manager_move", {"item": a, "list": "all"}, raw=True)
    assert ok and set(lean) == lean_keys and huddle_store(manager).item(a)["list"] == "all"
    ok, listed = call(manager, "task_manager_tasks_list", {"list": "12"})
    assert ok and all("thread" not in i for i in listed["items"])
    ok, listed = call(manager, "task_manager_tasks_list", {"list": "12", "include_thread": True})
    assert any("thread" in i for i in listed["items"])


def test_changes_sends_groups_only_when_changed_and_a_message_only_item_thin(manager):
    a, b = _items(manager, 2, 'all')
    store = huddle_store(manager)
    group = call(manager, "task_manager_group_create", {"list": "all", "name": "build"})[1]["id"]
    assert call(manager, "task_manager_move", {"item": a, "group": group})[0]
    ok, start = call(manager, "task_manager_tasks_list", {"list": "all"})
    store.post(b, "owner says hi", actor="joe")
    ok, one = call(manager, "task_manager_changes", {"since": start["cursor"], "list": "all"})
    assert ok and one["groups"] == [] and [m["item"] for m in one["messages"]] == [b]
    assert one["items"] == [{"id": b, "status": one["items"][0]["status"], "section": "open", "revision": one["items"][0]["revision"]}]
    assert set(one["items"][0]) == {"id", "status", "section", "revision"}
    store.update(b, actor="joe", text="reworded")
    store.post(b, "and a note", actor="joe")
    ok, two = call(manager, "task_manager_changes", {"since": one["cursor"], "list": "all"})
    assert ok and two["items"][0]["text"] == "reworded" and len(two["messages"]) == 1
    assert call(manager, "task_manager_group_update", {"group": group, "name": "builds"})[0]
    ok, three = call(manager, "task_manager_changes", {"since": two["cursor"], "list": "all"})
    assert ok and [g["name"] for g in three["groups"]] == ["builds"]
    ok, reset = call(manager, "task_manager_changes", {"since": 10**9, "list": "all"})
    assert ok and reset["reset"] and [g["name"] for g in reset["groups"]] == ["builds"]
    assert all("text" in i for i in reset["items"])


def test_changes_never_thins_an_item_the_pane_was_not_sent(manager):
    (a,) = _items(manager, 1)
    store = huddle_store(manager)
    cursor = call(manager, "task_manager_changes", {"since": 0, "list": "12", "include_thread": False})[1]["cursor"]
    store.post(a, "hello", actor="joe")
    ok, held = call(manager, "task_manager_changes", {"since": cursor, "list": "12"})
    assert ok and set(held["items"][0]) == {"id", "status", "section", "revision"}
    other = AgentCaller("ses_2", "ses_2", "ses_2", "pane", "write")
    store.post(a, "again", actor="joe")
    ok, fresh = call(manager, "task_manager_changes", {"since": cursor, "list": "12"}, caller=other)
    assert ok and fresh["items"][0]["text"] == "item 0"
    external = AgentCaller("mcp-token:t", "mcp-token:t", "mcp-token:t", "tok", "read")
    ok, ext = call(manager, "task_manager_changes", {"since": cursor, "list": "12"}, caller=external)
    assert ok and ext["items"][0]["text"] == "item 0"


def test_a_new_message_on_an_owner_reopened_item_comes_in_full(manager):
    (a,) = _items(manager, 1)
    store = huddle_store(manager)
    assert call(manager, "task_manager_update", {"item": a, "state": "waiting", "waiting_on": "the owner runs the staging restart", "wait_kind": "install"})[0]
    cursor = call(manager, "task_manager_tasks_list", {"list": "12"})[1]["cursor"]
    store.post(a, "not right", actor="joe")
    ok, body = call(manager, "task_manager_changes", {"since": cursor, "list": "12"})
    assert ok and body["items"][0]["state"] == "open" and "text" in body["items"][0]


def test_huddle_changes_answer_is_smaller_than_a_full_resend(manager):
    ids = _items(manager, 12, 'all')
    store = huddle_store(manager)
    group = call(manager, "task_manager_group_create", {"list": "all", "name": "build"})[1]["id"]
    for i in ids:
        call(manager, "task_manager_update", {"item": i, "review_description": "r" * 200, "review_where": "Settings > Huddle"})
    start = call(manager, "task_manager_tasks_list", {"list": "all"})[1]["cursor"]
    for i in ids:
        store.post(i, "a short reply", actor="joe")
    ok, lean = call(manager, "task_manager_changes", {"since": start, "list": "all"})
    external = AgentCaller("mcp-token:t", "mcp-token:t", "mcp-token:t", "tok", "read")
    ok, full = call(manager, "task_manager_changes", {"since": start, "list": "all"}, caller=external)
    assert group and len(json.dumps(lean)) < len(json.dumps(full)) // 2


def test_add_op_adds_across_lists_with_a_new_group_and_one_failure(manager, monkeypatch):
    monkeypatch.setattr(service, "project_names", lambda ctx: {"12": "carnivore"})
    ops = [{"op": "add", "text": "one", "group": "auth", "title": "first"},
           {"op": "add", "text": "two", "group": "auth"},
           {"op": "add", "text": "three", "list": "all", "kind": "info"},
           {"op": "add", "text": "x" * 100000}]
    ok, body = call(manager, "task_manager_batch_run", {"list_id": "mine", "ops": ops})
    assert ok and (body["applied"], body["failed"]) == (3, 1)
    good = body["results"][:3]
    assert all(set(r) == {"item_id", "ok", "state", "revision", "reaches_owner", "reaches_owner_reason"} and r["ok"] for r in good)
    assert body["results"][3]["ok"] is False and "error" in body["results"][3]
    store = huddle_store(manager)
    one, two, three = (store.item(r["item_id"]) for r in good)
    assert (one["list"], two["list"], three["list"]) == ("12", "12", "all")
    assert one["group"] == two["group"] and one["group"] is not None
