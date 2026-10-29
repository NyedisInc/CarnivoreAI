
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.core.session_tasks import service as tasks_service
from src.core.session_tasks.watch import SessionTasksWatch
from src.models.session_tasks import SessionTasks, TaskCounts, TaskItem
from tests.python.cplugs.huddle.test_task_manager_focus import add, call, client, setup  # noqa: F401

STEPS = "/api/v1/cplugs/huddle/steps"


def row(sid: str, project: int = 12, status: str = "working", family: str = "claude"):
    return SimpleNamespace(tmux_session=None, session=SimpleNamespace(id=sid), project_id=project, host_key="local", activity_status=status,
                           agent_family=family, label=f"label {sid}")


def tasklist(done: int, doing: int, todo: int, sid: str = "x") -> SessionTasks:
    items = [TaskItem(id=str(n), subject=f"step {n}", status=s)
             for n, s in enumerate(["completed"] * done + ["in_progress"] * doing + ["pending"] * todo)]
    return SessionTasks(state="ok" if items else "empty", session_id=sid, label=f"label {sid}", tasks=items,
                        counts=TaskCounts(pending=todo, in_progress=doing, completed=done))


@pytest.fixture
def world(setup, client, monkeypatch):
    rows = [row("ses_1"), row("ses_2"), row("ses_3", family="codex")]

    async def infos():
        return rows

    setup.app.state.session_manager.list_session_infos = infos
    lists = {"ses_1": tasklist(1, 1, 2), "ses_2": tasklist(0, 1, 1), "ses_3": SessionTasks(state="unsupported", session_id="ses_3")}

    async def fake_tasks_for(info, reader):
        return lists[info.session.id]

    monkeypatch.setattr(tasks_service, "tasks_for", fake_tasks_for)
    return SimpleNamespace(rows=rows, lists=lists)


def test_steps_needs_auth(setup):
    from fastapi.testclient import TestClient
    with TestClient(setup.app) as anonymous:
        assert anonymous.get(STEPS).status_code in (401, 403)


def test_a_claimed_item_gets_its_sessions_steps_and_an_unclaimed_working_session_gets_nothing(client, setup, world):
    item = add(client, "12", "build it")
    ok, _ = call(setup.manager, "task_manager_update", {"item": item, "state": "working"})
    assert ok
    body = client.get(STEPS).json()["lists"]["12"]
    assert body["items"][str(item)]["counts"] == {"pending": 2, "in_progress": 1, "completed": 1}
    assert [t["subject"] for t in body["items"][str(item)]["tasks"]][:2] == ["step 0", "step 1"]
    assert body == {"items": {str(item): body["items"][str(item)]}}


def test_an_unclaimed_working_session_alone_yields_no_line_under_the_project(client, setup, world):
    assert world.rows[0].activity_status == "working" and world.lists["ses_1"].counts.in_progress == 1
    assert client.get(STEPS).json() == {"lists": {}}


def test_all_complete_idle_and_other_project_sessions_show_nothing(client, setup, world):
    world.lists["ses_1"] = tasklist(2, 0, 0)
    world.lists["ses_2"] = tasklist(3, 0, 0)
    assert client.get(STEPS).json() == {"lists": {}}
    world.lists["ses_2"] = tasklist(0, 1, 0)
    assert client.get(STEPS).json() == {"lists": {}}


def test_an_item_that_leaves_working_drops_its_strip(client, setup, world):
    item = add(client, "12", "build it")
    call(setup.manager, "task_manager_update", {"item": item, "state": "working"})
    assert str(item) in client.get(STEPS).json()["lists"]["12"]["items"]
    call(setup.manager, "task_manager_update", {"item": item, "state": "open"})
    assert client.get(STEPS).json() == {"lists": {}}


def test_the_read_leases_the_watch_that_names_the_huddle_topic(client, setup, world):
    item = add(client, "12", "build it")
    call(setup.manager, "task_manager_update", {"item": item, "state": "working"})
    named: list[str] = []
    watch = SessionTasksWatch(notify=named.append, sleep=lambda s: asyncio.sleep(0))
    setup.app.state.session_tasks_watch = watch
    setup.app.state.session_tasks_reader = object()
    client.get(STEPS)
    assert asyncio.run(watch._tick()) is True  # noqa: SLF001
    assert named in ([], ["session_tasks:huddle"])
    world.lists["ses_1"] = tasklist(0, 1, 5)
    asyncio.run(watch._tick())  # noqa: SLF001
    assert named[-1] == "session_tasks:huddle"
