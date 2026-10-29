
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.huddle import changes_view, service
from src.cplugs.huddle.rules import CLAUDE, JOE, TaskManagerForbidden, TaskManagerInvalid
from src.cplugs.huddle.store import TaskManagerStore
from src.core.work.ladder import MIGRATIONS, SCHEMA_VERSION
from src.core.work.storage import WorkStorage
from tests.python.cplugs.huddle.test_task_manager_mcp import call, huddle_store, manager  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_routes import app  # noqa: F401


def test_rung_21_upgrades_an_old_file_once_and_is_idempotent(tmp_path: Path):
    path = tmp_path / "huddle.db"
    with sqlite3.connect(path) as conn:
        for step in MIGRATIONS[:20]:
            conn.executescript(step)
        conn.execute("INSERT INTO items (list_key, text, position, created_by, state, created_at, updated_at, created_seq, seq) "
                     "VALUES ('all', 'old', 0, 'joe', 'open', 1, 1, 1, 1)")
        conn.execute("PRAGMA user_version = 20")
    for _ in range(2):
        item = TaskManagerStore(WorkStorage(path.parent), notify=lambda t: None).list_items("all")["items"][0]
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert item["forked_from"] is None and "forked_from_title" not in item


def test_a_plain_fork_copies_title_text_list_and_group_and_threads_the_two(manager):
    store = huddle_store(manager)
    group = store.add("all", "g", actor=JOE)["id"]
    made = call(manager, "task_manager_add", {"list": "all", "text": "parent text", "title": "Parent", "group": "area"})[1]
    out = store.fork(made["id"], actor=JOE)
    fork, parent = out["fork"], out["parent"]
    assert (fork["text"], fork["title"], fork["list"], fork["group"]) == ("parent text", "Parent", "all", made["group"])
    assert fork["forked_from"] == made["id"] and fork["forked_from_title"] == "Parent" and parent["forked_from"] is None
    assert [m["text"] for m in fork["thread"]] == ["forked from Parent"] and fork["thread"][0]["kind"] == "info"
    assert [m["text"] for m in parent["thread"]] == ["forked into Parent"]
    assert fork["info_unread"] == 0 and parent["info_unread"] == 0
    assert fork["state"] == "open" and parent["state"] == "open" and group


@pytest.mark.parametrize("fork_state,parent_state", [
    ("review", None), (None, "todo"), ("open", "todo"), ("todo", "open"), ("working", "working")])
def test_claude_sets_either_or_both_states_in_one_call(manager, fork_state, parent_state):
    made = call(manager, "task_manager_add", {"list": "all", "text": "split me"})[1]
    args = {"item": made["id"], **({"fork_state": fork_state} if fork_state else {}), **({"parent_state": parent_state} if parent_state else {})}
    ok, body = call(manager, "task_manager_fork", args, raw=True)
    assert ok and body["ok"] and body["item_id"] == made["id"]
    store = huddle_store(manager)
    wanted_fork = "open" if fork_state in (None, "working") else fork_state
    wanted_parent = "open" if parent_state in (None, "working") else parent_state
    assert store.item(body["fork"]["item_id"])["state"] == wanted_fork == body["fork"]["state"]
    assert store.item(made["id"])["state"] == wanted_parent == body["parent"]["state"]
    if fork_state == "working":
        assert store.item(body["fork"]["item_id"])["status"] == "working"
    if parent_state is None:
        assert store.item(made["id"])["state"] == "open"


def test_claude_never_approves_and_a_refusal_rolls_the_whole_fork_back(manager):
    store = huddle_store(manager)
    made = call(manager, "task_manager_add", {"list": "all", "text": "keep"})[1]
    before = len(store.list_items("all")["items"])
    for args in ({"fork_state": "done"}, {"parent_state": "done"}, {"fork_state": "bogus"}):
        ok, text = call(manager, "task_manager_fork", {"item": made["id"], **args})
        assert not ok and ("approves" in text or "state must be" in text or "enum" in text.lower() or "must be one of" in text)
    assert len(store.list_items("all")["items"]) == before and store.item(made["id"])["thread"] == []


def test_the_owner_may_approve_either_side_and_an_approved_parent_stays_the_owners(manager):
    store = huddle_store(manager)
    made = store.add("all", "decide", actor=JOE)
    out = store.fork(made["id"], actor=JOE, fork_state="done", parent_state="todo")
    assert out["fork"]["state"] == "done" and out["parent"]["state"] == "todo"
    done = store.fork(made["id"], actor=JOE, parent_state="done")
    assert done["parent"]["state"] == "done"
    with pytest.raises(TaskManagerForbidden):
        store.fork(made["id"], actor=CLAUDE, parent_state="review")
    with pytest.raises(TaskManagerInvalid):
        store.fork(made["id"], actor=JOE, fork_state="working")


def test_title_text_list_group_and_review_fields_describe_the_fork(manager, monkeypatch):
    monkeypatch.setattr(service, "project_names", lambda ctx: {"12": "carnivore"})
    store = huddle_store(manager)
    made = call(manager, "task_manager_add", {"list": "all", "text": "orig", "title": "Orig"})[1]
    ok, body = call(manager, "task_manager_fork", {"item": made["id"], "title": "Piece", "text": "just this", "list": "12", "group": "area",
                                              "review_description": "check it", "fork_state": "review", "lean": False})
    fork = body["fork"]
    assert ok and (fork["title"], fork["text"], fork["list"], fork["state"], fork["review_description"]) == ("Piece", "just this", "12", "review", "check it")
    assert fork["forked_from"] == made["id"] and fork["group"] is not None


def test_lists_and_changes_expose_forked_from(manager):
    changes_view._SENT.clear()
    made = call(manager, "task_manager_add", {"list": "all", "text": "orig"})[1]
    ok, forked = call(manager, "task_manager_fork", {"item": made["id"]}, raw=True)
    ok, changes = call(manager, "task_manager_changes", {"since": 0, "list": "all"})
    assert any(i.get("forked_from") == made["id"] for i in changes["items"])
    ok, listed = call(manager, "task_manager_tasks_list", {"list": "all"})
    by_id = {i["id"]: i for i in listed["items"]}
    assert by_id[forked["fork"]["item_id"]]["forked_from"] == made["id"] and "forked_from" not in by_id[made["id"]]


def test_the_batch_fork_op_answers_both_sides_lean(manager):
    store = huddle_store(manager)
    made = call(manager, "task_manager_add", {"list": "all", "text": "orig"})[1]
    ok, body = call(manager, "task_manager_batch_run", {"list_id": "all", "ops": [
        {"op": "fork", "item_id": made["id"], "fork_state": "review", "parent_state": "todo"},
        {"op": "fork", "item_id": made["id"], "fork_state": "done"}]})
    first, second = body["results"]
    assert ok and body["applied"] == 1 and body["failed"] == 1 and not second["ok"]
    assert first["ok"] and first["fork"]["state"] == "review" and first["parent"]["state"] == "todo"
    assert store.item(first["fork"]["item_id"])["forked_from"] == made["id"]


def test_a_swarm_card_parent_takes_no_state_from_a_fork(manager):
    store = huddle_store(manager)
    card = store.add("all", "card", actor=JOE, swarm_ref="trust:1:ab")
    with pytest.raises(TaskManagerForbidden):
        store.fork(card["id"], actor=JOE, parent_state="done")
    with pytest.raises(TaskManagerForbidden):
        store.fork(card["id"], actor=CLAUDE)


def test_the_route_forks_as_the_owner_and_needs_auth(app):  # noqa: F811
    with TestClient(app) as anonymous:
        assert anonymous.post("/api/v1/cplugs/huddle/items/1/fork", json={}).status_code in (401, 403)
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as client:
        made = client.post("/api/v1/cplugs/huddle/lists/all/items", json={"text": "orig", "title": "Orig"}).json()
        done = client.post(f"/api/v1/cplugs/huddle/items/{made['id']}/fork", json={"fork_state": "done", "parent_state": "todo", "title": "Piece"})
        assert done.status_code == 200
        body = done.json()
        assert (body["fork"]["state"], body["fork"]["title"], body["fork"]["forked_from"]) == ("done", "Piece", made["id"])
        assert body["parent"]["state"] == "todo"
        assert client.post(f"/api/v1/cplugs/huddle/items/{made['id']}/fork", json={"fork_state": "nope"}).status_code == 400
        assert client.post("/api/v1/cplugs/huddle/items/999/fork", json={}).status_code == 404
        assert client.post(f"/api/v1/cplugs/huddle/items/{made['id']}/fork", json={"list": "77"}).status_code == 404
        assert client.post(f"/api/v1/cplugs/huddle/items/{made['id']}/fork", json={"list": "12"}).json()["fork"]["list"] == "12"


def test_the_tool_is_declared_and_a_read_token_never_sees_it():
    from src.core.mcp import tools
    from src.core.mcp.caller import AgentCaller
    assert any(d["name"] == "task_manager_fork" for d in tools.tool_definitions())
    assert "task_manager_fork" not in {d["name"] for d in tools.tool_definitions(AgentCaller("x", "x", "x", "tok", "read"))}

