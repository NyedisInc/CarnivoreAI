
from __future__ import annotations

import asyncio
import time

from src.cplugs.huddle import recurrence, schedule
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note, row  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_schedule import ITEMS, Env, call, env, iso  # noqa: F401

DAILY = {"freq": "daily", "time": "09:00"}
WEEKDAYS = {"freq": "weekly", "byweekday": [0, 1, 2, 3, 4], "time": "09:00"}


def repeat_item(client, env, rule=DAILY, text="stand-up notes") -> dict:
    item = env.add(client, text=text)
    done = client.patch(f"{ITEMS}/{item['id']}", json={"repeat": rule})
    assert done.status_code == 200, done.text
    return done.json()


def test_a_repeat_with_no_fire_at_starts_at_its_next_occurrence(client, env):
    item = repeat_item(client, env, WEEKDAYS)
    trigger = item["start_trigger"]
    assert trigger["repeat"] == WEEKDAYS and trigger["paused"] is False and trigger["fired_at"] is None
    assert trigger["fire_at"] == recurrence.next_after(WEEKDAYS, time.time()) or abs(trigger["fire_at"] - recurrence.next_after(WEEKDAYS, time.time())) < 5
    assert item["status"] == "scheduled"
    assert env.store.next_trigger_due() == trigger["fire_at"]


def test_a_fire_re_arms_for_the_next_occurrence(client, env):
    note(env.app, "ses_new", "12", 100.0)
    item = repeat_item(client, env)
    env.overdue(item["id"])
    first = env.store.claim_due_triggers()
    assert [i["id"] for i in first] == [item["id"]]
    after = env.trigger(item["id"])
    assert after["fired_at"] is None and after["last_fired_at"] is not None and after["last_error"] is None
    assert after["fire_at"] > time.time() and after["repeat"] == DAILY
    assert env.store.item(item["id"])["status"] == "scheduled"
    assert env.store.claim_due_triggers() == []
    assert env.store.next_trigger_due() == after["fire_at"]


def test_the_scheduler_delivers_a_repeat_once_per_occurrence(client, env):
    note(env.app, "ses_new", "12", 100.0)
    item = repeat_item(client, env)
    env.overdue(item["id"])
    assert asyncio.run(schedule.Scheduler(env.ctx).fire_due()) == 1
    assert len(env.pasted) == 1 and "came due" in env.pasted[0][1]
    assert asyncio.run(schedule.Scheduler(env.ctx).fire_due()) == 0 and len(env.pasted) == 1


def test_a_long_downtime_fires_once_and_never_a_burst(client, env):
    item = env.add(client)
    start = time.time() - 6 * 24 * 3600
    with env.ctx.storage.connect(True) as conn:
        conn.execute("INSERT INTO work_item_triggers (item_id, kind, fire_at, updated_at, repeat_rule, paused) VALUES (?, 'at', ?, ?, ?, 0)",
                     (item["id"], start, start, recurrence.dumps({"freq": "hourly", "interval": 4})))
    assert len(env.store.claim_due_triggers()) == 1
    assert env.store.claim_due_triggers() == []
    nxt = env.trigger(item["id"])["fire_at"]
    assert time.time() < nxt <= time.time() + 4 * 3600 + 1
    assert (nxt - start) % (4 * 3600) == 0


def test_downtime_across_several_daily_occurrences_fires_once(client, env):
    item = repeat_item(client, env)
    with env.ctx.storage.connect(True) as conn:
        conn.execute("UPDATE work_item_triggers SET fire_at = ? WHERE item_id = ?", (time.time() - 3 * 24 * 3600, item["id"]))
    assert len(env.store.claim_due_triggers()) == 1 and env.store.claim_due_triggers() == []
    assert env.trigger(item["id"])["fire_at"] > time.time()


def test_pause_holds_it_and_resume_re_arms_without_an_instant_fire(client, env):
    item = repeat_item(client, env)
    paused = client.patch(f"{ITEMS}/{item['id']}", json={"paused": True}).json()
    assert paused["start_trigger"]["paused"] is True and paused["status"] != "scheduled"
    env.overdue(item["id"])
    assert env.store.claim_due_triggers() == [] and env.store.next_trigger_due() is None
    resumed = client.patch(f"{ITEMS}/{item['id']}", json={"paused": False}).json()["start_trigger"]
    assert resumed["paused"] is False and resumed["fire_at"] > time.time()
    assert env.store.claim_due_triggers() == []
    assert env.store.next_trigger_due() == resumed["fire_at"]


def test_only_a_repeating_schedule_can_be_paused(client, env):
    item = env.add(client)
    assert client.patch(f"{ITEMS}/{item['id']}", json={"paused": True}).status_code == 400
    client.patch(f"{ITEMS}/{item['id']}", json={"fire_at": iso(3600)})
    assert client.patch(f"{ITEMS}/{item['id']}", json={"paused": True}).status_code == 400


def test_the_back_burner_pauses_a_repeat_and_taking_it_off_carries_on(client, env):
    note(env.app, "ses_new", "12", 100.0)
    item = repeat_item(client, env)
    client.patch(f"{ITEMS}/{item['id']}", json={"state": "todo"})
    env.overdue(item["id"])
    assert env.store.claim_due_triggers() == []
    parked = env.trigger(item["id"])
    assert parked["last_error"] is None and parked["fire_at"] > time.time() and parked["repeat"] == DAILY
    assert parked["last_fired_at"] is None
    client.patch(f"{ITEMS}/{item['id']}", json={"state": "open"})
    env.overdue(item["id"])
    assert len(env.store.claim_due_triggers()) == 1


def test_delete_stops_a_repeat_and_a_tick_does_not(client, env):
    a, b = repeat_item(client, env, text="a"), repeat_item(client, env, text="b")
    ticked = client.patch(f"{ITEMS}/{a['id']}", json={"approved": True}).json()
    assert ticked["state"] == "open" and ticked["start_trigger"]["repeat"] == DAILY
    assert client.delete(f"{ITEMS}/{b['id']}").status_code == 200
    assert env.store.next_trigger_due() == ticked["start_trigger"]["fire_at"]


def test_edit_and_stop(client, env):
    item = repeat_item(client, env)
    edited = client.patch(f"{ITEMS}/{item['id']}", json={"repeat": WEEKDAYS}).json()["start_trigger"]
    assert edited["repeat"] == WEEKDAYS
    same = client.patch(f"{ITEMS}/{item['id']}", json={"repeat": WEEKDAYS}).json()
    assert same["revision"] > 0 and same["start_trigger"]["fire_at"] == edited["fire_at"]
    one_time = client.patch(f"{ITEMS}/{item['id']}", json={"repeat": ""}).json()["start_trigger"]
    assert one_time["repeat"] is None and one_time["fire_at"] == edited["fire_at"]
    assert client.patch(f"{ITEMS}/{item['id']}", json={"repeat": {"freq": "daily"}}).status_code == 400
    stopped = client.patch(f"{ITEMS}/{item['id']}", json={"fire_at": ""}).json()
    assert stopped["start_trigger"] is None and env.store.next_trigger_due() is None


def test_an_explicit_fire_at_with_an_hourly_repeat_is_the_anchor(client, env):
    item = env.add(client)
    start = iso(1800)
    done = client.patch(f"{ITEMS}/{item['id']}", json={"fire_at": start, "repeat": {"freq": "hourly", "interval": 2}}).json()["start_trigger"]
    assert done["repeat"] == {"freq": "hourly", "interval": 2}
    assert 1790 < done["fire_at"] - time.time() < 1815


def test_a_failed_fire_keeps_a_repeat_scheduled_and_the_next_fire_clears_the_error(client, env):
    item = repeat_item(client, env)
    env.store.record_trigger_error(item["id"], "could not start a session")
    wire = env.store.item(item["id"])
    assert wire["start_trigger"]["last_error"] == "could not start a session" and wire["status"] == "scheduled"
    env.overdue(item["id"])
    env.store.claim_due_triggers()
    assert env.trigger(item["id"])["last_error"] is None


def test_claude_sets_pauses_resumes_and_stops_a_repeat_over_mcp(client, env):
    ok, added = call(env.app, "task_manager_add", {"list": "12", "text": "daily digest", "repeat": DAILY})
    assert ok and added["start_trigger"]["repeat"] == DAILY and added["start_trigger"]["kind"] == "at"
    item_id = added["id"]
    ok, paused = call(env.app, "task_manager_update", {"item": item_id, "paused": True})
    assert ok and paused["start_trigger"]["paused"] is True
    ok, resumed = call(env.app, "task_manager_update", {"item": item_id, "paused": False})
    assert ok and "paused" not in resumed["start_trigger"]
    ok, edited = call(env.app, "task_manager_update", {"item": item_id, "repeat": WEEKDAYS})
    assert ok and edited["start_trigger"]["repeat"] == WEEKDAYS
    ok, batch = call(env.app, "task_manager_batch_run", {"list_id": "12", "ops": [
        {"op": "update", "item_id": item_id, "repeat": {"freq": "monthly", "monthday": 31, "time": "08:00"}},
        {"op": "add", "text": "batched repeat", "repeat": {"freq": "hourly", "interval": 3}},
        {"op": "add", "text": "bad", "repeat": {"freq": "weekly", "time": "08:00"}},
        {"op": "add", "text": "paused add", "paused": True}]})
    assert ok and batch["applied"] == 2 and batch["failed"] == 2
    assert env.trigger(item_id)["repeat"]["monthday"] == 31
    ok, cleared = call(env.app, "task_manager_update", {"item": item_id, "repeat": ""})
    assert ok and "repeat" not in cleared["start_trigger"]
    ok, bad = call(env.app, "task_manager_update", {"item": item_id, "repeat": {"freq": "daily", "time": "99:00"}})
    assert not ok and "time" in bad
    ok, stopped = call(env.app, "task_manager_update", {"item": item_id, "fire_at": ""})
    assert ok and "start_trigger" not in stopped


def test_the_tool_schemas_offer_repeat_and_paused(client, env):
    from src.core.mcp import tools
    for name, has_paused in (("task_manager_add", False), ("task_manager_update", True)):
        props = next(d for d in tools.tool_definitions() if d["name"] == name)["inputSchema"]["properties"]
        assert "repeat" in props and ("paused" in props) is has_paused


def test_a_repeat_alone_keeps_a_pending_future_fire_at(client, env):
    item = env.add(client, text="check the build")
    when = iso(7200)
    assert client.patch(f"{ITEMS}/{item['id']}", json={"fire_at": when}).status_code == 200
    before = env.trigger(item["id"])["fire_at"]
    done = client.patch(f"{ITEMS}/{item['id']}", json={"repeat": {"freq": "hourly", "interval": 1}})
    assert done.status_code == 200, done.text
    after = env.trigger(item["id"])
    assert after["fire_at"] == before and after["repeat"] == {"freq": "hourly", "interval": 1}


def test_a_repeat_with_no_pending_fire_uses_the_next_occurrence(client, env):
    item = env.add(client, text="check the build")
    rule = {"freq": "hourly", "interval": 1}
    assert client.patch(f"{ITEMS}/{item['id']}", json={"repeat": rule}).status_code == 200
    assert abs(env.trigger(item["id"])["fire_at"] - recurrence.next_after(rule, time.time())) < 5
