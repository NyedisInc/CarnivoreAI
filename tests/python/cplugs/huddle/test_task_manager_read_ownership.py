
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.cplugs.huddle import held
from src.cplugs.huddle.rules import JOE
from src.core.mcp.caller import AgentCaller
from tests.python.cplugs.huddle.test_task_manager_mcp import call, huddle_store, manager  # noqa: F401

OWN = AgentCaller("ses_1", "cloude_a", "ses_1")
ORCHESTRATOR = AgentCaller("ses_2", "cloude_b", "ses_2")
TARGET = AgentCaller("ses_3", "cloude_c", "ses_3")


@pytest.fixture(autouse=True)
def three_sessions(manager):
    rows = [SimpleNamespace(tmux_session=None, session=SimpleNamespace(id=sid), project_id=project, host_key="local")
            for sid, project in (("ses_1", 12), ("ses_2", 99), ("ses_3", 99))]

    async def infos():
        return rows

    manager.list_session_infos = infos
    yield
    held.reset()


def status(manager, item_id):
    return huddle_store(manager).item(item_id)["status"]


def waiting(manager, list_key):
    return huddle_store(manager).summary()["lists"].get(list_key, {}).get("waiting_to_send", 0)


@pytest.mark.parametrize("tool,args", [("task_manager_tasks_list", {"list": "12"}), ("task_manager_changes", {"since": 0, "list": "12"}),
                                       ("task_manager_tasks_list", {"aggregate": True})])
def test_a_foreign_session_read_keeps_the_item_waiting_to_send_and_the_own_session_read_clears_it(manager, tool, args):
    item = huddle_store(manager).add("12", "fix it", actor=JOE)
    assert (status(manager, item["id"]), waiting(manager, "12")) == ("waiting_to_send", 1)
    ok, seen = call(manager, tool, args, caller=ORCHESTRATOR)
    assert ok
    assert (status(manager, item["id"]), waiting(manager, "12")) == ("waiting_to_send", 1)
    ok, seen = call(manager, tool, args, caller=OWN)
    assert ok and status(manager, item["id"]) == "open" and waiting(manager, "12") == 0


def test_a_foreign_read_answers_the_status_it_left_not_open(manager):
    huddle_store(manager).add("12", "fix it", actor=JOE)
    ok, listed = call(manager, "task_manager_tasks_list", {"list": "12"}, caller=ORCHESTRATOR)
    assert [i["status"] for i in listed["items"]] == ["waiting_to_send"]


def test_a_foreign_focus_records_nothing_and_the_own_focus_does(manager):
    item = huddle_store(manager).add("12", "fix it", actor=JOE)
    call(manager, "huddle_focus", {"list": "12", "items": [item["id"]]}, caller=ORCHESTRATOR)
    assert status(manager, item["id"]) == "waiting_to_send"
    call(manager, "huddle_focus", {"list": "12", "items": [item["id"]]}, caller=OWN)
    assert status(manager, item["id"]) == "open"


def test_the_shared_list_is_every_sessions_own(manager):
    item = huddle_store(manager).add("all", "fix it", actor=JOE)
    call(manager, "task_manager_tasks_list", {"list": "all"}, caller=ORCHESTRATOR)
    assert status(manager, item["id"]) == "open"


def test_the_session_a_held_tell_waits_for_reads_the_list_and_another_does_not(manager):
    item = huddle_store(manager).add("77", "ledgerbot fix", actor=JOE)
    held._holds["77"] = held.Hold("77", "ses_3", "Agent", held.HELD, "pane_dialog_open", "a dialog is open", 1.0, 2e12)
    call(manager, "task_manager_tasks_list", {"list": "77"}, caller=ORCHESTRATOR)
    assert (status(manager, item["id"]), waiting(manager, "77")) == ("waiting_to_send", 1)
    call(manager, "task_manager_tasks_list", {"list": "77"}, caller=TARGET)
    assert status(manager, item["id"]) == "open" and waiting(manager, "77") == 0


def test_a_dropped_hold_gives_its_target_no_claim(manager):
    item = huddle_store(manager).add("77", "ledgerbot fix", actor=JOE)
    held._holds["77"] = held.Hold("77", "ses_3", "Agent", held.GONE, "session_not_found", "gone", 1.0)
    call(manager, "task_manager_tasks_list", {"list": "77"}, caller=TARGET)
    assert status(manager, item["id"]) == "waiting_to_send"


def test_the_session_a_tell_was_delivered_to_reads_a_later_change_and_another_does_not(manager):
    store = huddle_store(manager)
    item = store.add("77", "ledgerbot fix", actor=JOE)
    store.record_send(["77"], store.current_cursor(), "ses_3")
    store.update(item["id"], actor=JOE, note="and this")
    assert status(manager, item["id"]) == "waiting_to_send"
    call(manager, "task_manager_tasks_list", {"list": "77"}, caller=ORCHESTRATOR)
    assert status(manager, item["id"]) == "waiting_to_send"
    call(manager, "task_manager_tasks_list", {"list": "77"}, caller=TARGET)
    assert status(manager, item["id"]) == "open"


def test_an_external_token_is_foreign_even_on_a_list_a_tell_named(manager):
    store = huddle_store(manager)
    item = store.add("12", "fix it", actor=JOE)
    external = AgentCaller("mcp-token:t", "mcp-token:t", "mcp-token:t", "tok", "read")
    call(manager, "task_manager_tasks_list", {"list": "12"}, caller=external)
    assert status(manager, item["id"]) == "waiting_to_send"
