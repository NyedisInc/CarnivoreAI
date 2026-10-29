
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import one_shot_routes
from src.api.auth import require_auth
from src.core.mcp import tools
from src.core.mcp.caller import AgentCaller
from src.cplugs.host import capabilities, runtime
from src.cplugs.huddle import callers, routes as huddle_routes, service
from src.cplugs.huddle.store import TaskManagerStore
from tests.python.cplugs.owner import turn_on

NOW = datetime(2026, 10, 4, 12, 0, 0)
UUIDS = {5: "uuid-created", 9: "uuid-adopted"}


def row(sid: str, row_id, tmux: str, minutes_ago: int = 0):
    session = SimpleNamespace(id=sid, agent_type="claude", last_activity=NOW - timedelta(minutes=minutes_ago))
    return SimpleNamespace(session=session, agent_type="claude", agent_family=None, project_id=12, project_name="carnivore",
                           label=tmux, tmux_session=tmux, activity_status="idle", host_key="local", session_row_id=row_id)


class World:

    def __init__(self) -> None:
        self.rows = [row("ses_a", 5, "cloude_a", 5), row("adopted:cloude_x", 9, "cloude_x", 9), row("ses_bystander", 77, "cloude_b", 1)]

    def recreate(self, old: str, new: str) -> None:
        was = next(r for r in self.rows if r.session.id == old)
        self.rows = [r for r in self.rows if r is not was] + [row(new, was.session_row_id, was.tmux_session)]


@pytest.fixture
def world(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(service, "project_names", lambda ctx: {"12": "carnivore"})
    monkeypatch.setattr(capabilities, "session_uuids", lambda ids: {i: UUIDS[i] for i in ids if i in UUIDS})
    app = FastAPI()
    app.include_router(huddle_routes.router, prefix="/api/v1")
    host = runtime.install(app, tmp_path)
    host.publish = lambda topic: None
    turn_on(host)
    state = World()

    async def infos():
        return state.rows

    manager = SimpleNamespace(list_session_infos=infos, gate_waited=True)
    app.state.session_manager = manager
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    pasted = []

    async def paste(request, session_id, text):
        pasted.append((session_id, text))
        return SimpleNamespace(pasted_bytes=len(text), submitted=True)

    monkeypatch.setattr(one_shot_routes, "paste_through_gates", paste)
    with TestClient(app) as client:
        yield SimpleNamespace(app=app, client=client, world=state, manager=manager, pasted=pasted,
                              storage=runtime.host_for(app).storage("huddle"))


def call(w, caller_id: str, name: str, args: dict):
    caller = AgentCaller(caller_id, "cloude_x", caller_id)
    result = asyncio.run(tools.call_tool(w.manager, caller, name, args))
    assert not result.get("isError"), result
    return json.loads(result["content"][0]["text"])


def picks(w):
    return w.client.get("/api/v1/cplugs/huddle/lists/12/sessions").json()


@pytest.mark.parametrize("old,new", [("ses_a", "ses_a_reborn"), ("adopted:cloude_x", "ses_x_reborn")])
def test_a_recreated_session_is_still_the_default_tell_target(world, old, new):
    call(world, old, "task_manager_add", {"list": "12", "text": "x"})
    assert picks(world)["default"] == old
    world.world.recreate(old, new)
    chosen = picks(world)
    assert (chosen["default"], chosen["reason"]) == (new, "last_task_manager_caller")
    told = world.client.post("/api/v1/cplugs/huddle/lists/12/send", json={}).json()
    assert told["target"] == new and world.pasted[-1][0] == new
    keys = {c[0] for c in callers.recent_callers(world.storage)}
    assert keys == {"uuid-created" if old == "ses_a" else "uuid-adopted"}


@pytest.mark.parametrize("old,new", [("ses_a", "ses_a_reborn"), ("adopted:cloude_x", "ses_x_reborn")])
def test_a_recreated_session_keeps_its_read_cursor(world, old, new):
    world.client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "already there"})
    listed = call(world, old, "task_manager_tasks_list", {"list": "12"})
    assert listed["cursor"] > 0
    world.world.recreate(old, new)
    world.client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "the owner adds after the read"})
    told = world.client.post("/api/v1/cplugs/huddle/lists/12/send", json={"target": new}).json()
    assert f"since {listed['cursor']}" in told["text"] and "since 0" not in told["text"]


def test_a_session_with_no_stored_row_keys_on_its_own_id(world):
    world.world.rows.append(row("ses_unstored", None, "cloude_u"))
    call(world, "ses_unstored", "task_manager_add", {"list": "12", "text": "x"})
    assert {c[0] for c in callers.recent_callers(world.storage)} == {"ses_unstored"}
    assert picks(world)["default"] == "ses_unstored"


def test_rows_written_before_the_change_resolve_and_then_move_onto_the_key(world):
    store = TaskManagerStore(world.storage, notify=lambda key: None)
    callers.note_caller(world.storage, "ses_a", "12", 100.0)
    store.note_read("ses_a", "12", 7)
    assert picks(world)["default"] == "ses_a"
    assert store.last_read("uuid-created", "12", "ses_a") == 7
    call(world, "ses_a", "task_manager_changes", {"list": "12", "since": 0})
    assert {c[0] for c in callers.recent_callers(world.storage)} == {"uuid-created"}
    assert store.last_read("uuid-created", "12") is not None and store.last_read("ses_a", "12") is None


def test_the_all_list_default_follows_a_recreate_too(world):
    call(world, "ses_a", "task_manager_tasks_list", {"list": "all"})
    world.world.recreate("ses_a", "ses_a_reborn")
    default = world.client.get("/api/v1/cplugs/huddle/lists/all/sessions").json()
    assert (default["default"], default["reason"]) == ("ses_a_reborn", "last_task_manager_caller")
