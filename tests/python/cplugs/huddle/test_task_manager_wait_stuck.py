
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone

import pytest

from src.cplugs.huddle import wait_runner, waits
from src.cplugs.huddle.answer_writer import AnswerWriter
from src.cplugs.huddle.roles import unstick
from src.cplugs.huddle.rules import TaskManagerInvalid, TaskManagerUseFireAt
from tests.python.cplugs.huddle.test_task_manager_mcp import call, huddle_store, manager  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_routes import app, client  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_schedule import ITEMS, env  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_waits import park, question_of, runner_at, told, wait_row  # noqa: F401


def future(hours: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).astimezone().isoformat(timespec="seconds")


def stuck(env, client) -> int:
    item = env.add(client)["id"]
    park(env.store, item)
    asyncio.run(runner_at(env, 2).expire_due())
    park(env.store, item, extend_reason="queued")
    asyncio.run(runner_at(env, 5).expire_due())
    return item



def test_a_wait_that_names_a_known_time_is_refused_with_a_code_and_the_fire_at_to_send(client, env):  # noqa: F811
    item = env.add(client)["id"]
    at = future(30)
    with pytest.raises(TaskManagerUseFireAt) as refused:
        park(env.store, item, wait_until=at)
    assert refused.value.code == "task_manager_use_fire_at" and at in str(refused.value) and "fire_at" in str(refused.value)
    assert env.store.item(item)["state"] != "waiting" and not wait_row(env.store, item)


def test_a_wait_until_with_no_offset_or_not_a_time_is_invalid_not_a_schedule(client, env):  # noqa: F811
    item = env.add(client)["id"]
    for bad in ("2026-10-30T09:00:00", "tomorrow morning"):
        with pytest.raises(TaskManagerInvalid, match="wait_until"):
            park(env.store, item, wait_until=bad)


def test_a_wait_with_no_known_time_still_parks_and_the_schedule_it_asks_for_works(client, env):  # noqa: F811
    item = env.add(client)["id"]
    assert park(env.store, item)["state"] == "waiting"
    other = env.add(client)["id"]
    scheduled = env.store.update(other, actor="claude", state="todo", fire_at=future(30))
    assert scheduled["state"] == "todo" and scheduled["start_trigger"]["fire_at"]


def test_the_agent_tool_takes_wait_until_and_refuses_it(manager, env, client):  # noqa: F811
    assert "wait_until" in waits.ARGS



def test_the_question_says_what_it_waited_on_since_when_and_has_exactly_four_options(client, env, told):  # noqa: F811
    item = stuck(env, client)
    question = question_of(env.store.item(item))
    assert "the staging restart" in question["text"] and "since" in question["text"]
    form = AnswerWriter(env.store).read(question["id"])["ask"]["questions"]
    assert [o["id"] for o in form[0]["options"]] == ["handle", "drop", "check", "until"]
    assert [o["label"] for o in form[0]["options"]] == ["i'll handle it", "drop it", "check it now", "give it until..."]
    assert "the staging restart" in form[0]["prompt"] and "since" in form[0]["prompt"] and form[1]["type"] == "datetime" and not form[1]["required"]


def test_give_it_until_schedules_the_task_at_that_time_and_clears_the_wait(client, env, told):  # noqa: F811
    item = stuck(env, client)
    at = future(48)
    posted = AnswerWriter(env.store).submit(question_of(env.store.item(item))["id"], {"q1": {"choice": "until"}, "q2": {"text": at}})
    after = env.store.item(item)
    assert posted["carnivore"] == {"category": "wait_stuck", "choice": "until"}
    assert after["state"] == "todo" and "wait" not in after and wait_row(env.store, item)["status"] == "settled"
    fire = datetime.fromtimestamp(after["start_trigger"]["fire_at"], tz=timezone.utc)
    assert fire == datetime.fromisoformat(at)


@pytest.mark.parametrize("typed", [None, "", "2020-01-01T09:00:00+00:00"])
def test_give_it_until_without_a_usable_time_refuses_the_whole_answer(client, env, told, typed):  # noqa: F811
    item = stuck(env, client)
    question = question_of(env.store.item(item))
    answers = {"q1": {"choice": "until"}, **({"q2": {"text": typed}} if typed else {})}
    with pytest.raises(TaskManagerInvalid):
        AnswerWriter(env.store).submit(question["id"], answers)
    assert not env.store.item(item)["start_trigger"] and not question_of(env.store.item(item))["answered"] and env.store.item(item)["state"] == "waiting"


def test_i_will_handle_it_parks_the_task_in_todo_for_the_owner(client, env, told):  # noqa: F811
    item = stuck(env, client)
    AnswerWriter(env.store).submit(question_of(env.store.item(item))["id"], {"q1": {"choice": "handle"}})
    after = env.store.item(item)
    assert after["state"] == "todo" and wait_row(env.store, item)["status"] == "settled"



def old_question(env, item: int) -> dict:
    import json
    from contextlib import closing

    question = question_of(env.store.item(item))
    old = {"v": 2, "context": "x", "questions": [{"id": "q1", "type": "single", "prompt": "this task is stuck waiting past two deadlines. what now?", "required": True,
                                                    "options": [{"id": "push", "label": "push it"}, {"id": "drop", "label": "drop it"}, {"id": "wait", "label": "wait longer"}]}]}
    with closing(env.store._connect(True)) as conn, conn:
        conn.execute("UPDATE work_messages SET parts = ? WHERE id = ?", (json.dumps(old), question["id"]))
    return question


@pytest.mark.parametrize("choice,state", [("push", "open"), ("drop", "todo"), ("wait", "waiting")])
def test_an_old_push_drop_wait_question_still_resolves(client, env, told, choice, state):  # noqa: F811
    item = stuck(env, client)
    question = old_question(env, item)
    posted = AnswerWriter(env.store).submit(question["id"], {"q1": {"choice": choice}})
    assert posted["carnivore"] == {"category": "wait_stuck", "choice": choice} and env.store.item(item)["state"] == state
    if choice == "wait":
        row = wait_row(env.store, item)
        assert row["status"] == "active" and row["deadline"] > time.time() + 20 * 3600 and row["extended"] == 1
    if choice == "push":
        sent = asyncio.run(unstick.after_answer(env.ctx, wait_runner._run, {**posted, "item": env.store.item(item)}))
        assert sent == {"list": "12", "status": "sent"}



def test_the_time_question_is_a_datetime_field_and_its_answer_is_an_iso_time_with_an_offset(client, env, told):  # noqa: F811
    item = stuck(env, client)
    question = question_of(env.store.item(item))
    form = AnswerWriter(env.store).read(question["id"])["ask"]["questions"]
    assert form[1]["type"] == "datetime" and not form[1]["required"]
    with pytest.raises(TaskManagerInvalid, match="offset"):
        AnswerWriter(env.store).submit(question["id"], {"q1": {"choice": "until"}, "q2": {"text": "2030-10-30T09:00:00"}})
    with pytest.raises(TaskManagerInvalid, match="ISO 8601"):
        AnswerWriter(env.store).submit(question["id"], {"q1": {"choice": "until"}, "q2": {"text": "soon"}})
    done = AnswerWriter(env.store).submit(question["id"], {"q1": {"choice": "drop"}, "q2": {"text": future(5)}})
    assert done["carnivore"]["choice"] == "drop"


def test_an_agent_can_not_ask_a_datetime_with_a_recommendation():
    from src.cplugs.huddle import rich_ask

    ok, _ = rich_ask.normalize([{"type": "datetime", "prompt": "when?"}])
    assert ok[0]["type"] == "datetime"
    with pytest.raises(TaskManagerInvalid, match="recommendation"):
        rich_ask.normalize([{"type": "datetime", "prompt": "when?", "recommend": {"text": "2030-01-01T00:00:00Z"}}])
