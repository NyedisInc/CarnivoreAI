
from __future__ import annotations

import asyncio
import json
from contextlib import closing

import pytest

from src.core.mcp import pending, tools
from src.cplugs.host import runtime
from src.cplugs.huddle import closure_undo, review_lock
from src.cplugs.huddle.rules import JOE, TaskManagerLocked, TaskManagerNotAllowed
from src.cplugs.huddle.store import TaskManagerStore
from tests.python.cplugs.huddle.test_task_manager_focus import CALLER, add, client, setup  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_mcp import full_echo

BASE = "/api/v1/cplugs/huddle"


@pytest.fixture(autouse=True)
def fresh_inbox(monkeypatch):
    monkeypatch.setattr(pending, "_store", pending.PendingActions())
    monkeypatch.setattr(pending, "MAX_WAIT_SECONDS", 0.05)


def call(setup, name: str, args: dict, raw: bool = False) -> tuple:
    result = asyncio.run(tools.call_tool(setup.manager, CALLER, name, args if raw else full_echo(name, args)))
    text = result["content"][0]["text"]
    return (False, text) if result.get("isError") else (True, json.loads(text))


def store_of(setup) -> TaskManagerStore:
    return TaskManagerStore(runtime.host_for(setup.app).storage("huddle"), notify=lambda key: None)


def fork(client, parent: int, title: str, **extra) -> int:
    answer = client.post(f"{BASE}/items/{parent}/fork", json={"title": title, **extra})
    assert answer.status_code == 200, answer.text
    return answer.json()["fork"]["id"]


def item(client, item_id: int) -> dict:
    return client.get(f"{BASE}/items/{item_id}").json()


def legacy_blocker(setup, item_id: int, text: str) -> None:
    with closing(store_of(setup)._connect(True)) as conn, conn:
        conn.execute("INSERT INTO work_blockers (item_id, kind, text, evidence, created_by, created_at) VALUES (?, 'install', ?, '', 'owner', 0)",
                     (item_id, text))




@pytest.mark.parametrize("body", [{"approved": True}, {"state": "done"}])
def test_the_owners_tick_is_locked_while_a_subtask_is_not_done(client, setup, body):
    parent = add(client, "12", "ship it")
    child = fork(client, parent, "wire the route")
    answer = client.patch(f"{BASE}/items/{parent}", json=body)
    assert answer.status_code == 409
    detail = answer.json()["detail"]
    assert detail["code"] == "task_manager_locked" and detail["reason"] == review_lock.SUBTASKS
    assert detail["blocking"]["subtasks"] == [{"id": child, "title": "wire the route", "state": "open"}]
    assert "1 subtask is not done yet" in detail["detail"] and "'wire the route'" in detail["detail"]
    assert item(client, parent)["state"] == "open"
    assert client.patch(f"{BASE}/items/{child}", json={"state": "review"}).status_code == 200
    assert client.patch(f"{BASE}/items/{parent}", json=body).status_code == 409
    assert client.patch(f"{BASE}/items/{child}", json={"approved": True}).status_code == 200
    assert client.patch(f"{BASE}/items/{parent}", json=body).status_code == 200
    assert item(client, parent)["state"] == "done"


def test_the_owners_tick_is_locked_by_a_hold_and_names_both(client, setup):
    parent = add(client, "12", "ship it")
    child = fork(client, parent, "write the test", parent_waits=True)
    assert item(client, parent)["state"] == "waiting"
    detail = client.patch(f"{BASE}/items/{parent}", json={"approved": True}).json()["detail"]
    assert detail["code"] == "task_manager_locked" and detail["reason"] == review_lock.BOTH
    assert [b["kind"] for b in detail["blocking"]["blockers"]] == ["children"]
    assert detail["blocking"]["subtasks"][0]["id"] == child
    assert item(client, parent)["state"] == "waiting" and item(client, parent)["blockers"]


def test_the_owners_tick_is_locked_by_an_uncleared_blocker_and_names_its_text(client, setup):
    lone = add(client, "12", "after the install")
    legacy_blocker(setup, lone, "the 1.17 install")
    detail = client.patch(f"{BASE}/items/{lone}", json={"approved": True}).json()["detail"]
    assert detail["code"] == "task_manager_locked" and detail["reason"] == review_lock.BLOCKERS
    assert "it still waits on the 1.17 install" in detail["detail"] and detail["blocking"]["subtasks"] == []


def test_a_stale_hold_does_not_lock_the_tick(client, setup):
    parent = add(client, "12", "ship it")
    child = fork(client, parent, "write the test", parent_waits=True)
    store = store_of(setup)
    with closing(store._connect(True)) as conn, conn:
        conn.execute("UPDATE work_items SET state = 'done' WHERE id = ?", (child,))
    assert client.patch(f"{BASE}/items/{parent}", json={"approved": True}).status_code == 200


def test_the_owners_fork_may_split_off_the_rest_and_close_but_not_past_another_open_subtask(client, setup):
    parent = add(client, "12", "ship it")
    split = client.post(f"{BASE}/items/{parent}/fork", json={"title": "the rest", "parent_state": "done"})
    assert split.status_code == 200 and split.json()["parent"]["state"] == "done"
    other = add(client, "12", "second")
    fork(client, other, "still open")
    before = len(store_of(setup).list_items("12")["items"])
    refused = client.post(f"{BASE}/items/{other}/fork", json={"title": "more", "parent_state": "done"})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "task_manager_locked"
    assert len(store_of(setup).list_items("12")["items"]) == before




def test_an_approved_close_request_is_not_applied_while_a_subtask_is_open(client, setup):
    parent = add(client, "12", "ship it")
    fork(client, parent, "wire the route")
    asked = asyncio.run(tools.call_tool(setup.manager, CALLER, "task_manager_state_request", {"item": parent, "action": "close", "reason": "duplicate"}))
    assert json.loads(asked["content"][0]["text"])["status"] == "pending"
    asyncio.run(pending.get_store().approve(pending.get_store().list()[0]["id"]))
    assert item(client, parent)["state"] == "open"
    assert any("not applied" in m["text"] and "'wire the route'" in m["text"] for m in item(client, parent)["thread"])




def test_the_agents_review_is_locked_until_every_subtask_is_in_review_or_done(client, setup):
    parent = add(client, "12", "ship it")
    ok, made = call(setup, "task_manager_fork", {"item": parent, "title": "write the test"})
    assert ok
    child = made["fork"]["item_id"]
    ok, text = call(setup, "task_manager_update", {"item": parent, "state": "review"})
    assert not ok and "1 subtask is not in review or done yet" in text and "'write the test' (open)" in text
    assert item(client, parent)["state"] == "open"
    assert call(setup, "task_manager_update", {"item": child, "state": "review"})[0]
    ok, out = call(setup, "task_manager_update", {"item": parent, "state": "review"})
    assert ok and out["state"] == "review"


def test_a_parked_subtask_still_locks_the_agents_review(client, setup):
    parent = add(client, "12", "ship it")
    child = fork(client, parent, "later")
    assert client.patch(f"{BASE}/items/{child}", json={"state": "todo"}).status_code == 200
    ok, text = call(setup, "task_manager_update", {"item": parent, "state": "review"})
    assert not ok and "'later' (todo)" in text


def test_the_store_raises_the_typed_lock_for_the_agents_review(client, setup):
    parent = add(client, "12", "ship it")
    fork(client, parent, "write the test")
    with pytest.raises(TaskManagerLocked) as caught:
        store_of(setup).update(parent, actor="claude", state="review")
    assert caught.value.reason == review_lock.SUBTASKS and caught.value.blocking["subtasks"][0]["title"] == "write the test"
    assert isinstance(caught.value, TaskManagerNotAllowed) and caught.value.status == 409




def test_the_agents_review_of_a_held_task_stays_waiting_and_names_the_subtask(client, setup):
    parent = add(client, "12", "ship it")
    ok, made = call(setup, "task_manager_fork", {"item": parent, "title": "write the test", "parent_waits": True})
    assert ok
    ok, out = call(setup, "task_manager_update", {"item": parent, "state": "review"})
    assert ok and out["state"] == "waiting"
    assert "'write the test' (open)" in out["blocked"]


def test_the_agents_review_of_a_task_with_an_uncleared_blocker_stays_waiting_and_names_it(client, setup):
    lone = add(client, "12", "after the install")
    legacy_blocker(setup, lone, "the 1.17 install")
    ok, out = call(setup, "task_manager_update", {"item": lone, "state": "review"})
    assert ok and out["state"] == "waiting" and "the 1.17 install" in out["blocked"]




def test_an_item_already_past_the_rule_is_left_and_only_its_next_tick_is_locked(client, setup):
    parent = add(client, "12", "ship it")
    assert client.patch(f"{BASE}/items/{parent}", json={"approved": True}).status_code == 200
    child = fork(client, parent, "follow up")
    assert item(client, parent)["state"] == "done" and item(client, child)["state"] == "open"
    assert client.patch(f"{BASE}/items/{parent}", json={"approved": False}).status_code == 200
    assert client.patch(f"{BASE}/items/{parent}", json={"approved": True}).status_code == 409


def test_a_cancel_is_not_a_tick_and_passes(client, setup):
    parent = add(client, "12", "ship it")
    fork(client, parent, "wire the route")
    store = store_of(setup)
    done = closure_undo.cancel_task(store, parent, store.item(parent)["revision"])
    assert done["item"]["state"] == "done"


def test_unticked_review_checks_never_lock_the_tick(client, setup):
    lone = add(client, "12", "ship it")
    ok, _ = call(setup, "task_manager_update", {"item": lone, "state": "review", "review_checks": ["tests pass"]})
    assert ok
    assert client.patch(f"{BASE}/items/{lone}", json={"approved": True}).status_code == 200


def test_the_owners_tick_of_a_card_op_or_a_swarm_lane_item_is_not_checked(setup):
    store = store_of(setup)
    card = store.add("all", "card", actor=JOE, swarm_ref="trust:1:ab")
    with closing(store._connect(True)) as conn, conn:
        row = conn.execute("SELECT * FROM work_items WHERE id = ?", (card["id"],)).fetchone()
        review_lock.check_tick(conn, row, "done", JOE, now=0.0)
