
from __future__ import annotations

import asyncio

from src.cplugs.huddle import lifecycle, schedule
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_schedule import ITEMS, arm, env, iso  # noqa: F401


def status_of(env, item_id: int) -> str:
    return env.store.item(item_id)["status"]


def test_the_section_sits_between_waiting_to_send_and_open():
    order = lifecycle.SECTIONS
    assert order.index("waiting_to_send") + 1 == order.index("scheduled") == order.index("open") - 1
    assert lifecycle.section_of("scheduled") == "scheduled" and "scheduled" in lifecycle.STATUSES


def test_a_pending_trigger_reads_scheduled_and_the_section_follows(client, env):
    item = env.add(client)
    body = arm(client, item["id"]).json()
    assert body["status"] == "scheduled" and body["section"] == "scheduled" and body["state"] == "open"
    assert env.store.summary()["lists"]["12"]["open"] == 1 and env.store.summary()["lists"]["12"]["incomplete"] == 1


def test_a_fired_trigger_leaves_scheduled(client, env):
    note(env.app, "ses_new", "12", 100.0)
    item = env.add(client)
    arm(client, item["id"])
    env.overdue(item["id"])
    asyncio.run(schedule.Scheduler(env.ctx).fire_due())
    assert env.trigger(item["id"])["fired_at"] is not None
    assert status_of(env, item["id"]) != "scheduled"


def test_a_failed_fire_returns_to_open_with_its_error(client, env):
    item = env.add(client)
    arm(client, item["id"])
    env.store.record_trigger_error(item["id"], "no session")
    assert env.trigger(item["id"])["last_error"] == "no session"
    assert status_of(env, item["id"]) != "scheduled"


def test_back_burner_never_reads_scheduled(client, env):
    item = env.add(client)
    arm(client, item["id"])
    assert client.patch(f"{ITEMS}/{item['id']}", json={"state": "todo"}).json()["status"] == "todo"


def test_an_approved_item_is_not_scheduled(client, env):
    item = env.add(client)
    arm(client, item["id"])
    body = client.patch(f"{ITEMS}/{item['id']}", json={"approved": True}).json()
    assert body["status"] != "scheduled" and body["start_trigger"] is None


def test_cancelling_the_time_returns_it_to_its_normal_status(client, env):
    item = env.add(client)
    arm(client, item["id"])
    body = client.patch(f"{ITEMS}/{item['id']}", json={"fire_at": ""}).json()
    assert body["status"] != "scheduled"


def test_a_reduced_row_without_trigger_columns_is_not_scheduled():
    row = {"state": "open", "kind": "", "created_by": "joe", "joe_seq": 0, "claude_read_seq": 0, "claude_working": 0}
    assert lifecycle.status(row, False) == "open"
