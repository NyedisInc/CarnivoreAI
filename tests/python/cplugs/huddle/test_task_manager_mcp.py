
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from src.cplugs.host import runtime
from src.cplugs.huddle import callers, service
from src.cplugs.huddle.store import TaskManagerStore
from src.core.mcp import tools
from src.core.mcp.caller import AgentCaller
from tests.python.cplugs.owner import turn_on

CALLER = AgentCaller("ses_1", "cloude_a", "ses_1")


@pytest.fixture
def manager(tmp_path: Path):
    app = FastAPI()
    host = runtime.install(app, tmp_path)
    host.publish = lambda topic: None
    turn_on(host)
    own = SimpleNamespace(tmux_session=None, label=None, session=SimpleNamespace(id="ses_1"), project_id=12, host_key="local")

    async def infos():
        return [own]

    return SimpleNamespace(app=app, gate_waited=True, list_session_infos=infos)


def huddle_store(manager) -> TaskManagerStore:
    return TaskManagerStore(runtime.host_for(manager.app).storage("huddle"), notify=lambda key: None)


LEAN_WRITES = {"task_manager_add", "task_manager_update", "task_manager_reply", "task_manager_ask", "task_manager_move", "task_manager_answered_set"}


def full_echo(name, args):
    return {"lean": False, **args} if name in LEAN_WRITES else args


def call(manager, name, args, caller=CALLER, raw=False):
    result = asyncio.run(tools.call_tool(manager, caller, name, args if raw else full_echo(name, args)))
    text = result["content"][0]["text"]
    return (False, text) if result.get("isError") else (True, json.loads(text))


def test_no_joe_only_action_is_offered_to_claude(manager):
    names = {d["name"] for d in tools.tool_definitions()}
    assert {"task_manager_tasks_list", "task_manager_changes", "task_manager_add", "task_manager_update", "task_manager_ask", "task_manager_reply"} <= names
    assert not {n for n in names if n.startswith("huddle_") and any(w in n for w in ("approve", "order"))}
    update = next(d for d in tools.tool_definitions() if d["name"] == "task_manager_update")
    enum = update["inputSchema"]["properties"]["state"]["enum"]
    assert enum == ["open", "working", "todo", "waiting", "review"]
    read_only = {d["name"] for d in tools.tool_definitions(AgentCaller("x", "x", "x", "tok", "read"))}
    assert "task_manager_tasks_list" in read_only and "task_manager_add" not in read_only


def test_claude_adds_marks_done_and_cannot_approve(manager):
    ok, item = call(manager, "task_manager_add", {"list": "mine", "text": "done: the list"})
    assert ok and item["list"] == "12" and item["created_by"] == "claude"
    ok, item = call(manager, "task_manager_update", {"item": item["id"], "state": "review"})
    assert ok and item["state"] == "review"
    ok, text = call(manager, "task_manager_update", {"item": item["id"], "state": "done"})
    assert not ok
    ok, text = call(manager, "task_manager_update", {"item": item["id"], "approved": True})
    assert not ok and "unknown argument" in text
    ok, text = call(manager, "task_manager_update", {"item": item["id"], "note": "x"})
    assert not ok
    assert huddle_store(manager).item(item["id"])["state"] == "review"


def test_changes_since_a_cursor_and_the_read_is_remembered_for_tell(manager):
    store = huddle_store(manager)
    ok, listed = call(manager, "task_manager_tasks_list", {"list": "all"})
    cursor = listed["cursor"]
    assert store.last_read("ses_1", "all") == cursor
    owner_item = store.add("all", "fix this", actor="joe")
    ok, moved = call(manager, "task_manager_changes", {"since": cursor, "list": "all"})
    assert ok and [i["id"] for i in moved["items"]] == [owner_item["id"]]
    ok, empty = call(manager, "task_manager_changes", {"since": moved["cursor"], "list": "all"})
    assert empty["items"] == [] and empty["messages"] == []
    assert store.last_read("ses_1", "all") == moved["cursor"]


def test_aggregate_lists_every_list_in_groups_and_all_stays_the_shared_list(manager, monkeypatch):
    monkeypatch.setattr(service, "project_names", lambda ctx: {"12": "carnivore"})
    store = huddle_store(manager)
    shared = store.add("all", "shared item", actor="joe")
    mine = store.add("12", "project item", actor="joe")
    ok, shared_only = call(manager, "task_manager_tasks_list", {"list": "all"})
    assert ok and [i["id"] for i in shared_only["items"]] == [shared["id"]]
    ok, grouped = call(manager, "task_manager_tasks_list", {"aggregate": True})
    assert ok and [g["list"] for g in grouped["groups"]] == ["all", "12"]
    assert [i["id"] for i in grouped["groups"][1]["items"]] == [mine["id"]]
    assert store.last_read("ses_1", "12") == grouped["cursor"]


def test_a_question_surfaces_from_the_asking_session(manager, monkeypatch):
    raised = []
    monkeypatch.setattr(service, "surface_question", lambda ctx, sid, item, message: raised.append((sid, item, message)) or True)
    item = huddle_store(manager).add("all", "x", actor="joe")
    ok, asked = call(manager, "task_manager_ask", {"item": item["id"], "text": "what did you mean?"})
    assert ok and asked["notified"] is True and raised == [("ses_1", item["id"], asked["message_id"])]
    assert asked["item"]["thread"][0]["kind"] == "question"
    ok, replied = call(manager, "task_manager_reply", {"item": item["id"], "text": "noted"})
    assert ok and len(raised) == 1


def test_an_external_tokens_write_waits_for_the_owner(manager, monkeypatch):
    from src.core.mcp import write_tools

    parked = []

    async def park(manager, caller, target_id, target_tmux, name, summary, shown, run, key):
        parked.append(name)
        return {"content": [{"type": "text", "text": json.dumps({"status": "pending", "id": "act_1"})}]}

    monkeypatch.setattr(write_tools, "park", park)
    external = AgentCaller("mcp-token:t", "mcp-token:t", "mcp-token:t", "tok", "write")
    ok, body = call(manager, "task_manager_add", {"list": "all", "text": "x"}, caller=external)
    assert ok and body["status"] == "pending" and parked == ["task_manager_add"]
    assert huddle_store(manager).list_items("all")["items"] == []


def test_claude_sets_kind_instead_of_prefixing_and_sees_numbers(manager):
    ok, added = call(manager, "task_manager_add", {"list": "all", "text": "pick a database", "kind": "question"})
    assert ok and added["kind"] == "question" and added["number"] == 1 and added["text"] == "pick a database"
    ok, second = call(manager, "task_manager_add", {"list": "all", "text": "shipped it"})
    ok, updated = call(manager, "task_manager_update", {"item": second["id"], "kind": "done"})
    assert ok and updated["kind"] == "done" and updated["number"] == 2
    ok, listed = call(manager, "task_manager_tasks_list", {"list": "all", "fields": ["kind"]})
    assert [(i["number"], i["kind"]) for i in listed["items"]] == [(1, "question"), (2, "done")]
    ok, moved = call(manager, "task_manager_changes", {"since": 0, "list": "all", "include_mine": True})
    assert all(set(i) == {"id", "status", "section", "revision"} for i in moved["items"])
    assert [(m["item"], m["kind"]) for m in moved["messages"]] == [(1, "question")]
    ok, text = call(manager, "task_manager_add", {"list": "all", "text": "x", "kind": "urgent"})
    assert not ok


def test_every_pane_tool_call_records_the_caller_for_tell(manager):
    storage = runtime.host_for(manager.app).storage("huddle")
    ok, item = call(manager, "task_manager_add", {"list": "mine", "text": "x"})
    assert ok and [(c[0], c[1]) for c in callers.recent_callers(storage)] == [("ses_1", "12")]
    other = AgentCaller("ses_2", "cloude_b", "ses_2")
    ok, _ = call(manager, "task_manager_reply", {"item": item["id"], "text": "y"}, caller=other)
    assert ok and callers.recent_callers(storage)[0][:2] == ("ses_2", "12")
    external = AgentCaller("ses_3", "x", "ses_3", "tok", "read")
    call(manager, "task_manager_tasks_list", {"list": "all"}, caller=external)
    assert "ses_3" not in {c[0] for c in callers.recent_callers(storage)}
