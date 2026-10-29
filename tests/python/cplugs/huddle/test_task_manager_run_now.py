
from __future__ import annotations

import asyncio

import pytest

from src.cplugs.huddle import schedule
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note, row  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_schedule import ITEMS, LISTS, Env, arm, call, env, iso  # noqa: F401

DAILY = {"freq": "daily", "time": "09:00"}


@pytest.fixture
def running(env):
    note(env.app, "ses_new", "12", 100.0)
    schedule._scheduler = schedule.Scheduler(env.ctx)
    yield env
    schedule._scheduler = None


def test_run_now_fires_once_through_the_scheduled_delivery(client, running):
    item = running.add(client)
    arm(client, item["id"], 3600)
    out = client.post(f"{ITEMS}/{item['id']}/run-now")
    assert out.status_code == 200
    assert len(running.pasted) == 1
    target, text = running.pasted[0]
    assert target == "ses_new" and "scheduled swarm came due" in text and f"item {item['id']}" in text
    trigger = out.json()["start_trigger"]
    assert trigger["fired_at"] is not None and trigger["last_error"] is None
    assert asyncio.run(schedule.Scheduler(running.ctx).fire_due()) == 0 and len(running.pasted) == 1


def test_run_now_re_arms_a_repeat_and_keeps_its_next_time(client, running):
    item = running.add(client)
    before = client.patch(f"{ITEMS}/{item['id']}", json={"repeat": DAILY}).json()["start_trigger"]
    after = client.post(f"{ITEMS}/{item['id']}/run-now").json()["start_trigger"]
    assert len(running.pasted) == 1
    assert after["repeat"] == DAILY and after["fired_at"] is None and after["fire_at"] == before["fire_at"]
    assert after["last_fired_at"] is not None
    running.overdue(item["id"])
    again = client.post(f"{ITEMS}/{item['id']}/run-now").json()["start_trigger"]
    assert again["fire_at"] > after["last_fired_at"] and len(running.pasted) == 2
    assert asyncio.run(schedule.Scheduler(running.ctx).fire_due()) == 0


def test_run_now_tells_an_unscheduled_item_and_refuses_the_rest(client, running):
    plain, parked, done = (running.add(client, text=t) for t in ("plain", "parked", "done"))
    assert client.post(f"{ITEMS}/{plain['id']}/run-now").json()["start_trigger"] is None and len(running.pasted) == 1
    client.patch(f"{ITEMS}/{parked['id']}", json={"state": "todo"})
    client.patch(f"{ITEMS}/{done['id']}", json={"approved": True})
    for refused in (parked, done):
        assert client.post(f"{ITEMS}/{refused['id']}/run-now").status_code == 400
    assert client.post(f"{ITEMS}/99999/run-now").status_code == 404
    assert len(running.pasted) == 1


def test_a_failed_run_now_keeps_the_error_on_the_row(client, env):
    env.set_rows([])
    item = env.add(client, list_key="all")
    arm(client, item["id"], 3600)
    schedule._scheduler = schedule.Scheduler(env.ctx)
    try:
        out = client.post(f"{ITEMS}/{item['id']}/run-now")
    finally:
        schedule._scheduler = None
    assert out.status_code == 200 and env.pasted == []
    assert "no running agent session" in out.json()["start_trigger"]["last_error"]


def test_run_now_is_refused_when_the_scheduler_is_not_running(client, env):
    item = env.add(client)
    assert schedule._scheduler is None
    assert client.post(f"{ITEMS}/{item['id']}/run-now").status_code == 400


def test_the_editor_adds_a_scheduled_item_with_instructions_and_a_repeat(client, env):
    added = client.post(f"{LISTS}/12/items", json={"text": "run the nightly check", "title": "nightly", "fire_at": iso(3600), "repeat": DAILY})
    assert added.status_code == 200
    body = added.json()
    assert body["title"] == "nightly" and body["text"] == "run the nightly check"
    assert body["start_trigger"]["repeat"] == DAILY and body["status"] == "scheduled"
    plain = client.post(f"{LISTS}/12/items", json={"text": "one shot", "fire_at": iso(60)}).json()
    assert plain["start_trigger"]["repeat"] is None and plain["start_trigger"]["fire_at"] is not None


def test_the_editor_edits_instructions_time_and_repeat_in_one_save(client, env):
    item = env.add(client, text="old words")
    arm(client, item["id"], 3600)
    saved = client.patch(f"{ITEMS}/{item['id']}", json={"text": "new words", "title": "t", "fire_at": iso(7200), "repeat": DAILY})
    assert saved.status_code == 200
    out = saved.json()
    assert out["text"] == "new words" and out["start_trigger"]["repeat"] == DAILY
    assert env.store.next_trigger_due() == out["start_trigger"]["fire_at"]


def test_claude_runs_an_item_now_with_huddle_update_and_the_batch(client, running):
    item = running.add(client)
    arm(client, item["id"], 3600)
    ok, out = call(running.app, "task_manager_update", {"item": item["id"], "fire_now": True})
    assert ok and out["start_trigger"]["fired_at"] is not None and len(running.pasted) == 1
    other = running.add(client, text="other")
    ok, batch = call(running.app, "task_manager_batch_run", {"list_id": "12", "ops": [{"op": "update", "item_id": other["id"], "fire_now": True}]})
    assert ok and batch["applied"] == 1 and len(running.pasted) == 2
    ok, text = call(running.app, "task_manager_update", {"item": item["id"], "fire_now": "nope"})
    assert ok
    assert len(running.pasted) == 2
