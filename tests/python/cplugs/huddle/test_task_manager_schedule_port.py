
from __future__ import annotations

import asyncio

from src.cplugs.huddle import schedule_port, triggers
from src.cplugs.sdk import ports
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_schedule import env, iso  # noqa: F401

DAILY = {"freq": "daily", "time": "09:00"}


def entries(env) -> dict:
    infos = asyncio.run(env.app.state.session_manager.list_session_infos())
    return asyncio.run(schedule_port.SchedulePort(env.ctx).by_session(infos))


def test_a_schedule_maps_to_the_session_its_fire_would_be_told_to(env):
    note(env.app, "ses_old", "12", 100.0)
    env.store.add("12", "later one-shot", actor="joe", title="later", fire_at=iso(7200))
    env.store.add("12", "sweep", actor="joe", title="sweep", fire_at=iso(1800), repeat=DAILY)
    got = entries(env)
    assert list(got) == ["ses_old"]
    assert [e["name"] for e in got["ses_old"]] == ["sweep", "later"]
    assert got["ses_old"][0]["retrying"] is True and got["ses_old"][1]["retrying"] is False
    assert all(e["enabled"] and not e["failed"] and e["next_fire_at"] for e in got["ses_old"])


def test_off_and_failed_and_sent_and_shared_and_sessionless_are_read_right(env):
    note(env.app, "ses_old", "12", 100.0)
    paused = env.store.add("12", "parked", actor="joe", title="parked", fire_at=iso(60), repeat=DAILY)["id"]
    env.store.update(paused, actor="joe", paused=True)
    broken = env.store.add("12", "broken", actor="joe", title="broken", fire_at=iso(120))["id"]
    env.store.record_trigger_error(broken, "not sent: nobody home")
    sent = env.store.add("12", "done", actor="joe", title="sent", fire_at=iso(30))["id"]
    env.store.claim_now(sent)
    env.store.add("all", "shared", actor="joe", title="shared", fire_at=iso(10))
    env.store.add("13", "elsewhere", actor="joe", title="nowhere", fire_at=iso(10))
    by_name = {e["name"]: e for e in entries(env)["ses_old"]}
    assert set(by_name) == {"parked", "broken"}
    assert by_name["parked"]["enabled"] is False and by_name["broken"]["failed"] is True and by_name["broken"]["retrying"] is False


def test_the_owner_of_an_item_does_not_steer_a_fire(env):
    note(env.app, "ses_old", "12", 100.0)
    item = env.store.add("12", "owned", actor="joe", title="owned", fire_at=iso(60))["id"]
    env.store.mark_working(item, "ses_new")
    assert list(entries(env)) == ["ses_old"]


def test_no_schedule_no_entries_and_the_port_follows_the_plugin(env):
    assert entries(env) == {}
    schedule_port.register(env.ctx)
    assert isinstance(ports.get(schedule_port.NAME), schedule_port.SchedulePort)
    schedule_port.unregister()
    assert ports.get(schedule_port.NAME) is None
    assert triggers.FIELD == "start_trigger"
