
from __future__ import annotations

import asyncio

from src.cplugs.huddle import lifecycle, schedule, triggers
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_schedule import ITEMS, env, iso  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_nudge_position import make_row

DAILY = {"freq": "daily", "time": "09:00"}


def thread_lines(env, item_id: int) -> list:
    with env.ctx.storage.connect(False) as conn:
        return [r[0] for r in conn.execute("SELECT text FROM work_messages WHERE item_id = ? AND kind = 'info' ORDER BY seq", (item_id,))]


def scheduled_waiting_item(client, env) -> int:
    note(env.app, "ses_old", "12", 100.0)
    item = env.add(client, text="timed work")["id"]
    client.patch(f"{ITEMS}/{item}", json={"fire_at": iso(3600)})
    env.store.update(item, actor="claude", state="waiting")
    return item


def test_part1_a_one_shot_fire_reaches_a_waiting_item_on_the_session_that_replaced_the_setter(client, env):  # noqa: F811
    item = scheduled_waiting_item(client, env)
    note(env.app, "ses_new", "12", 200.0)
    env.overdue(item)

    assert asyncio.run(schedule.Scheduler(env.ctx).fire_due()) == 1
    assert [target for target, _ in env.pasted] == ["ses_new"]
    fired = env.trigger(item)
    assert fired["fired_at"] is not None and fired["last_error"] is None
    assert env.store.item(item)["state"] == "waiting"


def test_part1_the_back_burner_no_longer_refuses_a_one_shot(client, env):  # noqa: F811
    note(env.app, "ses_old", "12", 100.0)
    item = env.add(client, text="parked")["id"]
    client.patch(f"{ITEMS}/{item}", json={"fire_at": iso(3600)})
    env.store.update(item, actor="claude", state="todo")
    env.overdue(item)
    assert [i["id"] for i in env.store.claim_due_triggers()] == [item]
    assert env.trigger(item)["last_error"] is None


def test_part2_the_nudge_skips_any_item_with_a_pending_one_shot_or_an_armed_repeat():
    pending = {"trigger_kind": "at", "trigger_fire_at": 9e9, "trigger_fired_at": None, "trigger_error": None, "trigger_repeat": None, "trigger_paused": 0}
    armed = {**pending, "trigger_repeat": '{"freq": "daily"}'}
    paused = {**armed, "trigger_paused": 1}
    for state, working in (("open", 0), ("open", 1), ("working", 1)):
        base = make_row(state=state, claude_working=working)
        item_status = lifecycle.status({**base, **pending}, False)
        assert lifecycle.position({**base, **pending}, item_status, idle=True) == lifecycle.EXTERNAL_WAIT, (state, working)
        assert lifecycle.position({**base, **armed}, lifecycle.status({**base, **armed}, False), idle=True) == lifecycle.EXTERNAL_WAIT
    base = make_row(state="open", claude_working=1)
    assert lifecycle.position({**base, **paused}, lifecycle.status({**base, **paused}, False), idle=True) == lifecycle.AGENT_IDLE
    assert lifecycle.position(base, lifecycle.status(base, False), idle=True) == lifecycle.AGENT_IDLE


def test_part3_a_refused_fire_posts_one_info_line_naming_the_reason(client, env):  # noqa: F811
    note(env.app, "ses_old", "12", 100.0)
    item = env.add(client, text="needs a decision")["id"]
    client.patch(f"{ITEMS}/{item}", json={"fire_at": iso(3600)})
    env.store.post(item, "which one?", actor="claude", kind="question")
    before = len(thread_lines(env, item))
    env.overdue(item)
    env.store.claim_due_triggers()
    lines = thread_lines(env, item)[before:]
    assert len(lines) == 1 and "not sent: the item is waiting on you" in lines[0]


def test_part3_a_failed_delivery_posts_its_reason_too(client, env):  # noqa: F811
    note(env.app, "ses_old", "12", 100.0)
    item = env.add(client, text="timed")["id"]
    before = len(thread_lines(env, item))
    env.store.record_trigger_error(item, "not sent: nobody home")
    lines = thread_lines(env, item)[before:]
    assert len(lines) == 1 and "not sent: nobody home" in lines[0]


def test_part4_parking_a_scheduled_item_waiting_is_accepted_with_expect_by_after_the_fire(client, env):  # noqa: F811
    from tests.python.cplugs.huddle.test_task_manager_waits import park
    note(env.app, "ses_old", "12", 100.0)
    item = env.add(client, text="timed")["id"]
    client.patch(f"{ITEMS}/{item}", json={"fire_at": iso(1800)})
    assert park(env.store, item, expect_by=iso(7200))["state"] == "waiting"
    assert env.store.update(item, actor="claude", fire_at=iso(900), state="waiting")["state"] == "waiting"



def woke_lines(env, item_id: int) -> list:
    return [t for t in thread_lines(env, item_id) if t.startswith("scheduled wake-up sent to ")]


def test_2568_a_one_shot_delivery_names_the_session_it_went_to(client, env):  # noqa: F811
    item = scheduled_waiting_item(client, env)
    note(env.app, "ses_new", "12", 200.0)
    env.overdue(item)
    asyncio.run(schedule.Scheduler(env.ctx).fire_due())
    lines = woke_lines(env, item)
    asyncio.run(asyncio.sleep(0))
    assert [target for target, _ in env.pasted] == ["ses_new"]
    assert len(lines) == 1 and len(lines[0]) > len("scheduled wake-up sent to ")


def test_2568_a_repeat_posts_only_when_the_target_changes(client, env):  # noqa: F811
    note(env.app, "ses_old", "12", 100.0)
    item = env.add(client, text="daily")["id"]
    client.patch(f"{ITEMS}/{item}", json={"fire_at": iso(3600), "repeat": DAILY})
    for _ in range(2):
        env.overdue(item)
        asyncio.run(schedule.Scheduler(env.ctx).fire_due())
    assert len(woke_lines(env, item)) == 1
    note(env.app, "ses_new", "12", 300.0)
    env.overdue(item)
    asyncio.run(schedule.Scheduler(env.ctx).fire_due())
    assert len(woke_lines(env, item)) == 2 and woke_lines(env, item)[0] != woke_lines(env, item)[1]


def test_2568_a_refused_fire_writes_only_the_refusal_line(client, env):  # noqa: F811
    note(env.app, "ses_old", "12", 100.0)
    item = env.add(client, text="needs a decision")["id"]
    client.patch(f"{ITEMS}/{item}", json={"fire_at": iso(3600)})
    env.store.post(item, "which one?", actor="claude", kind="question")
    env.overdue(item)
    asyncio.run(schedule.Scheduler(env.ctx).fire_due())
    assert woke_lines(env, item) == []


def test_2568_the_line_says_when_the_target_was_the_lead():
    from src.cplugs.huddle import fire_line
    assert fire_line.line("Agent - Trader", True) == "scheduled wake-up sent to Agent - Trader (the list's lead)"
    assert fire_line.line("Agent - Trader", False) == "scheduled wake-up sent to Agent - Trader"



def fire_tagged(client, env, tag: str, *, lead: str = "") -> tuple:
    from src.cplugs.huddle.roles import tags
    from tests.python.cplugs.huddle.roles_rig import BASE
    note(client.app, "ses_old", "12", 100.0)
    note(client.app, "ses_new", "12", 200.0)
    item = env.add(client, text="timed work")["id"]
    client.patch(f"{ITEMS}/{item}", json={"fire_at": iso(3600)})
    if lead:
        assert client.put(f"{BASE}/lists/12/lead", json={"session": lead}).status_code == 200
    if tag:
        tags.set_tag(env.store, item, tag)
    env.overdue(item)
    asyncio.run(schedule.Scheduler(env.ctx).fire_due())
    return item, woke_lines(env, item)


def test_2568_step2_a_live_tagged_session_gets_the_fire_with_no_reason(client, env):  # noqa: F811
    item, lines = fire_tagged(client, env, "ses_old")
    assert [t for t, _ in env.pasted] == ["ses_old"]
    assert len(lines) == 1 and "own session is gone" not in lines[0]


def test_2568_step2_a_gone_tagged_session_falls_back_to_the_lead_and_says_why(client, env):  # noqa: F811
    item, lines = fire_tagged(client, env, "ses_ghost", lead="ses_old")
    assert [t for t, _ in env.pasted] == ["ses_old"]
    assert len(lines) == 1 and lines[0].endswith("(the list's lead; the task's own session is gone)")


def test_2568_step2_a_gone_tag_with_no_lead_falls_back_to_the_list_and_says_why(client, env):  # noqa: F811
    item, lines = fire_tagged(client, env, "ses_ghost")
    assert len(env.pasted) == 1 and len(lines) == 1 and lines[0].endswith("(the task's own session is gone)")


def test_2568_step2_an_untagged_item_goes_to_the_lead_as_before(client, env):  # noqa: F811
    item, lines = fire_tagged(client, env, "", lead="ses_old")
    assert [t for t, _ in env.pasted] == ["ses_old"]
    assert len(lines) == 1 and lines[0].endswith("(the list's lead)")


def test_2568_step2_the_line_gives_the_reason_for_a_fall_back():
    from src.cplugs.huddle import fire_line
    assert fire_line.line("A", True, True) == "scheduled wake-up sent to A (the list's lead; the task's own session is gone)"
    assert fire_line.line("A", False, True) == "scheduled wake-up sent to A (the task's own session is gone)"
