
from __future__ import annotations

import asyncio
from contextlib import closing

import pytest

from src.cplugs.huddle import blockers, lineage, schedule, wait_runner
from src.cplugs.huddle.rules import TaskManagerInvalid, TaskManagerLocked
from tests.python.cplugs.huddle.test_task_manager_mcp import call, huddle_store, manager  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_routes import app, client  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_schedule import env  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_waits import INSTALL, ROUTE, fresh_rate_limit, park, told  # noqa: F401

HOLD = {"wait_kind": "children"}


def fork_held(store, parent: int, by: str = "u-1") -> dict:
    return store.fork(parent, actor="claude", claimed_by=by, parent_waits=True)["fork"]


def lineage_of(store, item: int) -> list:
    with closing(store._connect(False)) as conn:
        return lineage.for_item(conn, item)


def hold_rows(store, item: int) -> list:
    return blockers.BlockerStore(store).for_item(item, include_cleared=True)


def release(env) -> int:
    return asyncio.run(wait_runner.WaitRunner(env.ctx).release_holds())



def test_a_fork_with_parent_waits_parks_the_parent_on_its_forks_and_a_second_fork_joins_the_same_hold(manager):  # noqa: F811
    store = huddle_store(manager)
    parent = store.add("all", "big task", actor="joe")["id"]
    fork_held(store, parent)
    shown = store.item(parent)
    assert shown["state"] == "waiting" and [(b["kind"], b["holding"], b["created_by"]) for b in shown["blockers"]] == [("children", 1, "u-1")]
    assert lineage_of(store, parent)[-1]["to"] == "waiting"
    fork_held(store, parent)
    again = store.item(parent)["blockers"]
    assert len(again) == 1 and again[0]["holding"] == 2 and len(hold_rows(store, parent)) == 1


def test_a_hold_is_refused_with_a_parent_state_on_a_done_or_parked_task_or_on_a_swarm_lane_item(manager):  # noqa: F811
    store = huddle_store(manager)
    parent = store.add("all", "t", actor="joe")["id"]
    with pytest.raises(TaskManagerInvalid):
        store.fork(parent, actor="claude", parent_state="review", parent_waits=True)
    parked = store.add("all", "parked", actor="joe")["id"]
    park(store, parked)
    with pytest.raises(TaskManagerInvalid):
        fork_held(store, parked)
    done = store.add("all", "d", actor="joe")["id"]
    store.update(done, actor="joe", state="done")
    with pytest.raises(TaskManagerInvalid):
        store.fork(done, actor="joe", parent_waits=True)
    swarm = store.add("all", "s", actor="joe")["id"]
    with closing(store._connect(True)) as conn, conn:
        conn.execute("UPDATE work_items SET lane = 'swarm' WHERE id = ?", (swarm,))
    with pytest.raises(TaskManagerInvalid):
        fork_held(store, swarm)
    assert all(not hold_rows(store, i) for i in (parent, parked, done, swarm))


def test_wait_kind_children_holds_later_only_with_an_open_fork_and_takes_no_time(manager):  # noqa: F811
    store = huddle_store(manager)
    parent = store.add("all", "t", actor="joe")["id"]
    with pytest.raises(TaskManagerInvalid):
        store.update(parent, actor="claude", state="waiting", wait=HOLD, wait_by="u-2")
    store.fork(parent, actor="claude")
    with pytest.raises(TaskManagerInvalid):
        store.update(parent, actor="claude", state="waiting", wait={**HOLD, "expect_by": "2030-01-01T00:00:00+00:00"}, wait_by="u-2")
    held = store.update(parent, actor="claude", state="waiting", wait=HOLD, wait_by="u-2")
    assert held["state"] == "waiting" and held["blockers"][0]["created_by"] == "u-2" and "wait" not in held
    with pytest.raises(TaskManagerInvalid):
        park(store, parent)


@pytest.mark.parametrize("child_state, holds", [("open", True), ("waiting", True), ("review", False), ("done", False), ("todo", False)])
def test_r67_which_children_hold_their_parent(manager, child_state, holds):  # noqa: F811
    store = huddle_store(manager)
    parent = store.add("all", "t", actor="joe")["id"]
    child = fork_held(store, parent)["id"]
    store.update(child, actor="joe", state=child_state)
    with closing(store._connect(False)) as conn:
        assert bool(blockers.holding(conn, parent)) is holds


def test_r67_a_deleted_child_is_dropped(manager):  # noqa: F811
    store = huddle_store(manager)
    parent = store.add("all", "t", actor="joe")["id"]
    child = fork_held(store, parent)["id"]
    store.delete(child, actor="joe")
    with closing(store._connect(False)) as conn:
        assert blockers.holding(conn, parent) == 0



def test_an_agents_move_of_a_held_parent_stays_waiting_says_why_and_the_stop_is_in_its_history(manager):  # noqa: F811
    store = huddle_store(manager)
    parent = store.add("all", "t", actor="joe")["id"]
    fork_held(store, parent)
    ok, answer = call(manager, "task_manager_update", {"item": parent, "state": "review"})
    assert ok and answer["state"] == "waiting" and answer["blocked"].startswith("held by its forked tasks (1 still open")
    stop = lineage_of(store, parent)[-1]
    assert (stop["from"], stop["to"], stop["by"], stop["detail"]) == ("waiting", "waiting", "carnivore", "blocked")
    store.fork(parent, actor="claude", parent_state="open")
    assert store.item(parent)["state"] == "waiting" and lineage_of(store, parent)[-1]["detail"] == "blocked"


def test_a_hold_with_no_holding_child_left_is_cleared_at_the_check_and_the_move_passes(manager):  # noqa: F811
    store = huddle_store(manager)
    parent = store.add("all", "t", actor="joe")["id"]
    child = fork_held(store, parent)["id"]
    store.update(child, actor="joe", state="done")
    moved = store.update(parent, actor="claude", state="review")
    assert moved["state"] == "review" and "blockers" not in moved and hold_rows(store, parent)[0]["cleared_by"] == "carnivore"


def test_the_owners_reply_keeps_the_hold_and_his_tick_waits_for_the_forks(manager):  # noqa: F811
    store = huddle_store(manager)
    replied = store.add("all", "r", actor="joe")["id"]
    fork_held(store, replied)
    store.post(replied, "go ahead without them", actor="joe", kind="reply")
    assert store.item(replied)["state"] == "waiting" and hold_rows(store, replied)[0]["cleared_at"] is None
    ticked = store.add("all", "k", actor="joe")["id"]
    child = fork_held(store, ticked)["id"]
    with pytest.raises(TaskManagerLocked):
        store.update(ticked, actor="joe", state="done")
    assert store.item(ticked)["state"] == "waiting" and hold_rows(store, ticked)[0]["cleared_at"] is None
    store.update(child, actor="joe", state="done")
    assert store.update(ticked, actor="joe", state="done")["state"] == "done" and hold_rows(store, ticked)[0]["cleared_at"] is not None



def test_the_last_child_finishing_hands_the_parent_back_open_once_and_tells_its_agent(client, env, told):  # noqa: F811
    parent = env.add(client)["id"]
    first, second = fork_held(env.store, parent)["id"], fork_held(env.store, parent)["id"]
    env.store.update(first, actor="claude", state="review")
    assert release(env) == 0 and env.store.item(parent)["state"] == "waiting"
    env.store.update(second, actor="joe", state="todo")
    assert release(env) == 1 and release(env) == 0
    after = env.store.item(parent)
    assert after["state"] == "open" and "blockers" not in after
    assert any(m["text"] == "cleared: its forked tasks are done" and m["author_key"] == "carnivore" for m in after["thread"])
    last = lineage_of(env.store, parent)[-1]
    assert (last["to"], last["by"], last["detail"]) == ("open", "carnivore", "children_done")
    assert told == [("u-1", "12")]


def test_a_parent_parked_in_todo_has_its_hold_cleared_but_is_not_moved(client, env, told):  # noqa: F811
    parent = env.add(client)["id"]
    child = fork_held(env.store, parent)["id"]
    assert env.store.update(parent, actor="claude", state="todo")["state"] == "todo"
    env.store.update(child, actor="joe", state="done")
    assert release(env) == 1 and env.store.item(parent)["state"] == "todo" and told == []


def test_the_scheduler_releases_a_finished_hold_at_boot_without_a_new_write(client, env, told):  # noqa: F811
    parent = env.add(client)["id"]
    child = fork_held(env.store, parent)["id"]
    env.store.update(child, actor="joe", state="done")

    async def scenario():
        schedule.start(env.ctx)
        try:
            for _ in range(100):
                if env.store.item(parent)["state"] == "open":
                    break
                await asyncio.sleep(0.05)
        finally:
            schedule.stop()

    asyncio.run(scenario())
    assert env.store.item(parent)["state"] == "open"



def test_the_agent_clears_a_hold_with_huddle_wait_update(manager):  # noqa: F811
    store = huddle_store(manager)
    parent = store.add("all", "t", actor="joe")["id"]
    ok, forked = call(manager, "task_manager_fork", {"item": parent, "parent_waits": True})
    assert ok and store.item(parent)["state"] == "waiting"
    ok, answer = call(manager, "task_manager_wait_update", {"item": parent, "result": "cleared", "reason": "doing the rest myself"})
    assert ok and answer["state"] == "open"
    assert hold_rows(store, parent)[0]["cleared_by"] not in ("", "owner", "carnivore", None)
    assert any(m["text"] == "cleared: doing the rest myself" for m in store.item(parent)["thread"])
    ok, text = call(manager, "task_manager_fork", {"item": parent, "parent_state": "waiting"})
    assert not ok and "parent_waits" in text


def test_the_owners_route_clears_a_hold_and_a_bare_call_cannot(client, env, told, monkeypatch):  # noqa: F811
    from src.cplugs.huddle import routes_wait

    parent = env.add(client)["id"]
    fork_held(env.store, parent)
    client.app.dependency_overrides.clear()
    assert client.post(ROUTE.format(parent), json={"token": "anything", "result": "cleared"}).status_code == 403
    assert env.store.item(parent)["state"] == "waiting"

    async def owner(request):
        return True

    monkeypatch.setattr(routes_wait, "has_valid_bearer", owner)
    done = client.post(ROUTE.format(parent), json={"result": "cleared"})
    assert done.status_code == 200 and done.json()["state"] == "open" and hold_rows(env.store, parent)[0]["cleared_by"] == "owner"


def test_the_owners_fork_route_takes_parent_waits(client, env):  # noqa: F811
    parent = env.add(client)["id"]
    made = client.post(f"/api/v1/cplugs/huddle/items/{parent}/fork", json={"parent_waits": True})
    assert made.status_code == 200 and made.json()["parent"]["state"] == "waiting" and made.json()["parent"]["blockers"][0]["created_by"] == "owner"
    refused = client.post(f"/api/v1/cplugs/huddle/items/{parent}/fork", json={"parent_waits": True, "parent_state": "open"})
    assert refused.status_code == 400


def test_only_the_hold_kind_is_ever_written(manager):  # noqa: F811
    store = huddle_store(manager)
    parent = store.add("all", "t", actor="joe")["id"]
    fork_held(store, parent)
    with closing(store._connect(False)) as conn:
        assert [r[0] for r in conn.execute("SELECT DISTINCT kind FROM work_blockers")] == ["children"]
