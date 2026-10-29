
from __future__ import annotations

from contextlib import closing

import pytest

from src.cplugs.huddle import lineage, service
from src.cplugs.huddle.answer_writer import AnswerWriter
from src.cplugs.huddle.nudge_store import NudgeStore
from tests.python.cplugs.huddle.test_task_manager_nudge_sweep import ITEMS, LISTS, Rig, rig  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note, row  # noqa: F401


def stall(rig, client, **kw) -> dict:
    item = rig.add(client)
    rig.own(item["id"])
    rig.switch(client)
    for hours in (1.1, 3.2, 6.3, 10.5):
        rig.sweep(hours)
    return rig.item(item["id"])


def open_question(item: dict) -> dict:
    return [m for m in item["thread"] if m["kind"] == "question" and not m["answered"]][-1]


def answer(rig, item: dict, choice: str) -> dict:
    AnswerWriter(rig.store).submit(open_question(item)["id"], {"q1": {"choice": choice}})
    return rig.item(item["id"])


def test_the_stall_is_one_typed_question_from_carnivore_with_three_options_and_raises_no_toast(client, rig, monkeypatch):
    monkeypatch.setattr(service, "surface_question", lambda *a, **k: pytest.fail("a Carnivore question raises no toast (R90)"))
    rig.ctx.toast = lambda *a, **k: pytest.fail("a Carnivore question raises no toast (R90)")
    asked = stall(rig, client)
    question = open_question(asked)
    assert asked["status"] == "question" and len(rig.pasted) == 3 and rig.toasts == []
    assert (question["author"], question["author_key"], question["category"]) == ("claude", "carnivore", "stall")
    form = AnswerWriter(rig.store).read(question["id"])
    assert form["typed"] is True and [o["id"] for o in form["ask"]["questions"][0]["options"]] == ["unstick", "park", "cancel"]
    assert "idle for" in form["ask"]["context"] and "ship" not in form["ask"]["context"]
    rig.sweep(30.0)
    assert len([m for m in rig.item(asked["id"])["thread"] if m["kind"] == "question"]) == 1


def test_answering_park_moves_the_task_to_todo_by_the_owner_and_unstick_and_cancel_leave_it_open(client, rig):
    parked = answer(rig, stall(rig, client), "park")
    assert parked["state"] == "todo"
    with closing(rig.store._connect(False)) as conn:
        last = lineage.for_item(conn, parked["id"])[-1]
    assert (last["to"], last["detail"]) == ("todo", "stall_park") or (last.get("to_state"), last.get("detail")) == ("todo", "stall_park")


@pytest.mark.parametrize("choice", ["unstick", "cancel"])
def test_unstick_and_cancel_leave_the_task_open_and_restart_the_nudge_count(client, rig, choice):
    after = answer(rig, stall(rig, client), choice)
    assert after["state"] == "open" and after["status"] != "question" and "nudge" not in after


def test_a_waiting_task_is_never_a_candidate(client, rig):
    item = rig.add(client)
    rig.store.update(item["id"], actor="joe", state="waiting")
    assert rig.nudge_store.candidates("12") == []


def test_an_open_task_whose_session_is_busy_is_never_due(client, rig):
    rig.set_rows([rig.fresh("ses_new", state="working")])
    item = rig.add(client)
    rig.own(item["id"])
    rig.switch(client)
    for hours in (1.5, 5.0, 40.0):
        rig.sweep(hours)
    assert rig.pasted == [] and rig.item(item["id"])["status"] != "question"


def test_a_task_nobody_owns_is_offered_but_never_stalls(client, rig):
    item = rig.add(client)
    rig.switch(client)
    for hours in (1.1, 3.2, 6.3, 10.5, 40.0):
        rig.sweep(hours)
    assert len(rig.pasted) == 3 and rig.item(item["id"])["status"] != "question"


def test_the_project_switch_is_on_by_default_and_an_explicit_off_stays_off(client, rig):
    rig.add(client)
    assert rig.nudge_store.nudge_lists() == ["12"] and rig.nudge_store.enabled() is True
    assert client.get(f"{LISTS}/12/prefs").json()["nudge"] is True
    assert {l["key"]: l["nudge"] for l in client.get(LISTS).json()["lists"]}["12"] is True
    assert client.get(f"{LISTS}/all/prefs").json()["nudge"] is False
    rig.switch(client, False)
    assert rig.nudge_store.nudge_lists() == [] and rig.nudge_store.enabled() is False
    assert client.get(f"{LISTS}/12/prefs").json()["nudge"] is False
    rig.switch(client, True)
    assert rig.nudge_store.nudge_lists() == ["12"]


def test_with_no_switch_written_an_idle_session_is_nudged_about_its_open_task(client, rig):
    item = rig.add(client)
    rig.sweep(1.2)
    assert len(rig.pasted) == 1 and rig.item(item["id"])["nudge"]["count"] == 1


def test_a_reply_nobody_picks_up_stalls_into_a_question(client, rig):
    item = rig.add(client)
    rig.own(item["id"])
    client.patch(f"{ITEMS}/{item['id']}", json={"state": "review"})
    client.post(f"{ITEMS}/{item['id']}/messages", json={"text": "and the second part?"})
    assert rig.item(item["id"])["state"] == "open"
    with closing(rig.store._connect(True)) as conn, conn:
        conn.execute("UPDATE work_items SET claude_read_seq = joe_seq WHERE id = ?", (item["id"],))
    for hours in (1.1, 3.2, 6.3, 10.5):
        rig.sweep(hours)
    assert len(rig.pasted) == 3 and rig.item(item["id"])["status"] == "question"
