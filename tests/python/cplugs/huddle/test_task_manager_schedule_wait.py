
from __future__ import annotations

from src.cplugs.huddle import triggers, wait_runner
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_schedule import ITEMS, call, env, iso  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_waits import INSTALL, park  # noqa: F401

DAILY = {"freq": "daily", "time": "09:00"}


def scheduled_item(client, env, *, fire_in: float = 3600) -> int:
    note(env.app, "ses_new", "12", 100.0)
    item = env.add(client, text="scheduled work")["id"]
    client.patch(f"{ITEMS}/{item}", json={"fire_at": iso(fire_in)})
    return item


def stamp_legacy_waiting_skip(env, item: int) -> None:
    with env.ctx.storage.connect(True) as conn:
        conn.execute("UPDATE work_item_triggers SET fired_at = fire_at, last_error = ? WHERE item_id = ?", (triggers.SKIP_WAITING, item))


def stamp_legacy_parked_skip(env, item: int) -> None:
    with env.ctx.storage.connect(True) as conn:
        conn.execute("UPDATE work_item_triggers SET fired_at = fire_at, last_error = ? WHERE item_id = ?", (triggers.SKIP_PARKED, item))


def test_a_fire_on_a_waiting_item_is_delivered_not_skipped(client, env):  # noqa: F811
    item = scheduled_item(client, env)
    env.store.update(item, actor="claude", state="waiting")
    env.overdue(item)
    assert [i["id"] for i in env.store.claim_due_triggers()] == [item]
    assert env.trigger(item)["last_error"] is None


def test_a_legacy_waiting_skip_comes_back_when_the_owner_moves_the_item(client, env):  # noqa: F811
    item = scheduled_item(client, env)
    env.store.update(item, actor="claude", state="waiting")
    stamp_legacy_waiting_skip(env, item)
    client.patch(f"{ITEMS}/{item}", json={"state": "open"})
    assert env.trigger(item)["last_error"] is None and env.trigger(item)["fired_at"] is None
    assert [i["id"] for i in env.store.claim_due_triggers()] == [item]


def test_a_legacy_waiting_skip_comes_back_when_the_wait_hands_it_back(client, env):  # noqa: F811
    item = scheduled_item(client, env)
    env.store.update(item, actor="claude", state="waiting")
    stamp_legacy_waiting_skip(env, item)
    wait_runner.hand_back(env.store, item, "the wait ran out", "wait_expired")
    assert [i["id"] for i in env.store.claim_due_triggers()] == [item]


def test_a_fire_skipped_on_the_owners_turn_comes_back_when_he_answers(client, env):  # noqa: F811
    item = scheduled_item(client, env)
    env.store.post(item, "which one?", actor="claude", kind="question")
    env.overdue(item)
    assert env.store.claim_due_triggers() == []
    assert env.trigger(item)["last_error"] == triggers.SKIP_JOE
    env.store.post(item, "the second", actor="joe", kind="reply")
    assert [i["id"] for i in env.store.claim_due_triggers()] == [item]


def test_a_legacy_back_burner_skip_comes_back_when_it_is_released_into_a_wait(client, env):  # noqa: F811
    item = scheduled_item(client, env)
    env.store.update(item, actor="claude", state="todo")
    stamp_legacy_parked_skip(env, item)
    env.store.update(item, actor="claude", state="waiting")
    assert [i["id"] for i in env.store.claim_due_triggers()] == [item]


def test_a_tick_after_a_skip_leaves_no_trigger_and_nothing_fires(client, env):  # noqa: F811
    item = scheduled_item(client, env)
    env.store.update(item, actor="claude", state="waiting")
    env.overdue(item)
    env.store.claim_due_triggers()
    client.patch(f"{ITEMS}/{item}", json={"approved": True})
    assert env.trigger(item) is None
    assert env.store.claim_due_triggers() == []


def test_a_move_to_the_back_burner_keeps_a_legacy_skip_and_does_not_fire(client, env):  # noqa: F811
    item = scheduled_item(client, env)
    env.store.update(item, actor="claude", state="waiting")
    stamp_legacy_waiting_skip(env, item)
    env.store.update(item, actor="claude", state="todo")
    assert env.trigger(item)["last_error"] == triggers.SKIP_WAITING
    assert env.store.claim_due_triggers() == []


def test_a_repeating_schedule_may_sit_behind_a_wait(client, env):  # noqa: F811
    note(env.app, "ses_new", "12", 100.0)
    item = env.store.add("12", "sweep", actor="joe", fire_at=iso(1800), repeat=DAILY)["id"]
    assert park(env.store, item, expect_by=iso(3600))["state"] == "waiting"


def test_the_owner_may_park_a_scheduled_item_in_waiting(client, env):  # noqa: F811
    item = scheduled_item(client, env, fire_in=1800)
    assert env.store.update(item, actor="joe", state="waiting")["state"] == "waiting"


def test_schedules_list_all_means_every_list(app, client, env):  # noqa: F811
    env.store.add("12", "in a project", actor="joe", fire_at=iso(600))
    env.store.add("all", "in the shared list", actor="joe", fire_at=iso(900))
    ok, everything = call(app, "task_manager_schedules_list", {"list": "all"})
    assert ok and {s["list"] for s in everything["schedules"]} == {"12", "all"}
    ok, omitted = call(app, "task_manager_schedules_list", {})
    assert ok and omitted["schedules"] == everything["schedules"]


def test_a_fire_is_delivered_when_the_item_only_holds_an_unread_answer_for_the_owner(client, env):  # noqa: F811
    item = scheduled_item(client, env)
    env.store.post(item, "ok, going ahead", actor="claude", kind="answer", quote_text="start with the schema")
    env.overdue(item)
    assert [i["id"] for i in env.store.claim_due_triggers()] == [item]


def test_a_fire_is_delivered_when_the_item_only_holds_an_unread_notify_info(client, env):  # noqa: F811
    item = scheduled_item(client, env)
    env.store.post(item, "progress: half done", actor="claude", kind="info", notify=True)
    env.overdue(item)
    assert [i["id"] for i in env.store.claim_due_triggers()] == [item]


def test_a_fire_is_still_skipped_when_the_item_holds_an_open_question(client, env):  # noqa: F811
    item = scheduled_item(client, env)
    env.store.post(item, "which one?", actor="claude", kind="question")
    env.overdue(item)
    assert env.store.claim_due_triggers() == []
    assert env.trigger(item)["last_error"] == triggers.SKIP_JOE
