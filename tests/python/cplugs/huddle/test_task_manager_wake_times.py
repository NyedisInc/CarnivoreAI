
from __future__ import annotations

import asyncio

import pytest

from src.cplugs.huddle.roles.store import RoleStore

from src.cplugs.host import runtime
from src.cplugs.huddle import schedule_port, schedule_wakes, scheduled, triggers, wake_target
from src.cplugs.huddle.roles import tags
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note, pasted  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_schedule import iso
from tests.python.cplugs.huddle.test_task_manager_tagged_schedule import ctx_of
from tests.python.cplugs.huddle.test_task_manager_tags import SLEEPER, World, add, store_of
from tests.python.cplugs.huddle.test_task_manager_tagged_schedule import world  # noqa: F401

ASLEEP = [{"session_uuid": SLEEPER, "project_id": 12}]


def schedule(client, item: int, seconds: float) -> None:
    assert client.patch(f"/api/v1/cplugs/huddle/items/{item}", json={"fire_at": iso(seconds)}).status_code == 200


def wakes(world, asleep=ASLEEP) -> dict:
    return asyncio.run(schedule_wakes.wake_times(ctx_of(world.app), asleep))


def test_a_scheduled_item_tagged_to_a_sleeping_agent_wakes_it_at_its_fire_time(client, world):
    world.sleeper()
    item = add(client)
    schedule(client, item, 3600)
    tags.set_tag(store_of(world.app), item, SLEEPER)
    fire_at = store_of(world.app).item(item)["start_trigger"]["fire_at"]
    assert wakes(world) == {SLEEPER: fire_at} and fire_at > 0


def test_the_earliest_of_two_schedules_wins(client, world):
    world.sleeper()
    late, soon = add(client, "late"), add(client, "soon")
    schedule(client, late, 7200)
    schedule(client, soon, 600)
    for item in (late, soon):
        tags.set_tag(store_of(world.app), item, SLEEPER)
    assert wakes(world)[SLEEPER] == store_of(world.app).item(soon)["start_trigger"]["fire_at"]


def test_a_fire_told_to_a_live_session_wakes_nobody(client, world):
    world.sleeper()
    tagged_live, plain = add(client, "a"), add(client, "b")
    for item in (tagged_live, plain):
        schedule(client, item, 600)
    tags.set_tag(store_of(world.app), tagged_live, "ses_other")
    assert wakes(world) == {}


def test_an_untagged_fire_wakes_the_newest_sleeper_only_when_the_project_has_no_live_session(client, world):
    world.sleeper()
    item = add(client)
    schedule(client, item, 600)
    assert wakes(world) == {}
    world.live[:] = [row for row in world.live if getattr(row, "project_id", None) != 12]
    assert list(wakes(world)) == [SLEEPER]


def test_a_gone_tag_falls_to_a_sleeping_lead_and_a_live_tag_wakes_nobody(world):
    world.sleeper()
    reader = schedule_wakes._Reader(ctx_of(world.app), None)
    reader._leads = {"12": SLEEPER}
    wake = lambda tag: asyncio.run(schedule_wakes._tagged_target(reader, "12", tag, {SLEEPER}))  # noqa: E731
    assert wake("ses_ghost") == SLEEPER
    assert wake("ses_new") == ""


def test_nothing_wakes_for_a_sent_one_shot_a_paused_repeat_no_due_time_or_the_shared_list(client, world):
    world.sleeper()
    base = {"id": 1, "list": "12", "start_trigger": {"fire_at": 99.0, "paused": False, "repeat": None, "fired_at": None, "last_error": None}}
    assert schedule_wakes._firing(base) == 99.0
    assert schedule_wakes._firing({**base, "start_trigger": {**base["start_trigger"], "fired_at": 50.0}}) is None
    assert schedule_wakes._firing({**base, "start_trigger": {**base["start_trigger"], "repeat": {"every": 1}, "paused": True}}) is None
    assert schedule_wakes._firing({**base, "start_trigger": {**base["start_trigger"], "fire_at": None}}) is None
    assert schedule_wakes._firing({**base, "list": "all"}) is None
    assert wakes(world, []) == {}


def test_a_schedule_change_wakes_the_listing(app, monkeypatch):
    woken = []
    monkeypatch.setattr(schedule_port, "listing_wake", lambda state: lambda: woken.append(state))
    port = schedule_port.SchedulePort(ctx_of(app))
    port._app_state = app.state
    port.subscribe()
    try:
        triggers.nudge()
        triggers.wrote()
    finally:
        port.unsubscribe()
    assert len(woken) == 2
    triggers.nudge()
    assert len(woken) == 2


NEWER = "u-newer-sleeper"


def only_asleep(world) -> list:
    world.live[:] = [row for row in world.live if getattr(row, "project_id", None) != 12]
    world.asleep[:] = [{"session_uuid": NEWER, "project_id": 12, "name": "newer"}, {"session_uuid": SLEEPER, "project_id": 12, "name": "sleeper"}]
    return world.asleep


def test_an_untagged_fire_is_listed_and_clocked_for_the_same_asleep_session_the_fire_wakes(client, world):
    asleep = only_asleep(world)
    item = add(client)
    schedule(client, item, 600)
    store = store_of(world.app)
    RoleStore(store).set_lead("12", SLEEPER, "pinned")
    pings = asyncio.run(scheduled.build(ctx_of(world.app)))["schedules"][0]["pings"]
    assert (pings["session"], pings["session_key"]) == (None, SLEEPER)
    assert list(wakes(world, asleep)) == [SLEEPER]


def test_with_no_lead_the_newest_sleeper_is_listed_and_clocked(client, world):
    asleep = only_asleep(world)
    item = add(client)
    schedule(client, item, 600)
    pings = asyncio.run(scheduled.build(ctx_of(world.app)))["schedules"][0]["pings"]
    assert pings["session_key"] == NEWER and list(wakes(world, asleep)) == [NEWER]


def test_the_wake_target_rule_alone():
    sleepers = [{"session_uuid": "n", "project_id": 5}, {"session_uuid": "l", "project_id": 9}, {"session_uuid": "o", "project_id": 5}]
    assert wake_target.untagged_wake_target("5", "", sleepers) == "n"
    assert wake_target.untagged_wake_target("5", "l", sleepers) == "l"
    assert wake_target.untagged_wake_target("5", "gone", sleepers) == "n"
    assert wake_target.untagged_wake_target("all", "l", sleepers) is None and wake_target.untagged_wake_target("7", "", sleepers) is None
