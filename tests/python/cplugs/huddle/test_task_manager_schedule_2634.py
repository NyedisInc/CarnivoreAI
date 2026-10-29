
from __future__ import annotations

from src.cplugs.huddle import triggers
from tests.python.cplugs.huddle.test_task_manager_recurring import DAILY, repeat_item
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_schedule import ITEMS, env, iso  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_schedule_2560 import thread_lines


def parked_one_shot(client, env) -> int:  # noqa: F811
    note(env.app, "ses_old", "12", 100.0)
    item = env.add(client, text="NVR RAID at risk")["id"]
    client.patch(f"{ITEMS}/{item}", json={"fire_at": iso(3600)})
    env.store.update(item, actor="claude", state="todo")
    env.overdue(item)
    return item


def test_a_one_time_fire_on_the_back_burner_unparks_the_task_and_delivers(client, env):  # noqa: F811
    item = parked_one_shot(client, env)
    before = len(thread_lines(env, item))
    assert [i["id"] for i in env.store.claim_due_triggers()] == [item]
    assert env.store.item(item)["state"] == "open"
    trigger = env.trigger(item)
    assert trigger["fired_at"] is not None and trigger["last_error"] is None
    lines = thread_lines(env, item)[before:]
    assert any("status changed from todo to open" in line for line in lines)
    assert not any("not sent" in line for line in lines)


def test_a_repeat_on_the_back_burner_stays_paused_and_undelivered(client, env):  # noqa: F811
    note(env.app, "ses_new", "12", 100.0)
    item = repeat_item(client, env)["id"]
    env.store.update(item, actor="claude", state="todo")
    env.overdue(item)
    assert env.store.claim_due_triggers() == []
    assert env.store.item(item)["state"] == "todo"
    assert env.trigger(item)["repeat"] == DAILY


def test_a_one_time_fire_on_an_item_waiting_on_joe_is_still_skipped(client, env):  # noqa: F811
    note(env.app, "ses_old", "12", 100.0)
    item = env.add(client, text="needs a decision")["id"]
    client.patch(f"{ITEMS}/{item}", json={"fire_at": iso(3600)})
    env.store.post(item, "which one?", actor="claude", kind="question")
    env.overdue(item)
    assert env.store.claim_due_triggers() == []
    assert env.trigger(item)["last_error"] == triggers.SKIP_JOE
