
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import httpx
import pytest
from fastapi import FastAPI

import src.config  # noqa: F401
from src.api import automation_placement_routes as routes, automation_routes, blueprints_launch, blueprints_peer_member, blueprints_routes
from src.api.auth import require_auth
from src.core.automations import models as m, run_sessions, targets
from src.core.automations.scheduler import Context
from src.core.automations.store import AutomationStore
from src.core.automations.store_schema import storage_for
from src.core.automations.targets import blueprint
from src.core.pack.jobs import boot
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import JobError
from src.core.pack.session_place import automation as placement_store, create as create_mod, decide as decide_mod
from src.core.pack.session_place.create import PlacedSession
from src.core.pack.session_place.types import SessionPlacement
from src.models.blueprints_launch import LaunchedSession

TARGET = {"kind": "blueprint_launch", "blueprint_uuid": "bp-1", "members": None}
COMMAND = {"kind": "command", "command": "echo hi"}


class Env(SimpleNamespace):
    pass


@pytest.fixture()
def env(tmp_path: Path, monkeypatch) -> Env:
    monkeypatch.setitem(targets.RUNNERS, "blueprint_launch", blueprint.run)
    monkeypatch.setitem(targets.VALIDATORS, "blueprint_launch", lambda target: None)
    store = AutomationStore(storage_for(tmp_path))
    jobs = JobStore(tmp_path / "state")
    monkeypatch.setitem(boot._built, "engine", SimpleNamespace(store=jobs))
    run_sessions._marks.clear(), run_sessions._by_ses_id.clear()
    e = Env(store=store, jobs=jobs, launched=[], placed=[], members=[], cancelled=[])

    async def fake_call(operation, *args, **kwargs):
        return SimpleNamespace(spec=SimpleNamespace(sessions=e.members))

    async def fake_launch(request, index, member, root, consents, cols, rows, existing=None):
        e.launched.append(index)
        n = len(e.launched)
        return SimpleNamespace(state="launched", problem=None, session=LaunchedSession(
            id=f"ses_{n}", tmux_session=f"carnivore_{n}", session_row_id=100 + n, session_uuid=f"uuid-{n}"))

    monkeypatch.setattr(blueprints_routes, "call", fake_call)
    monkeypatch.setattr(blueprints_launch, "launch_member", fake_launch)
    monkeypatch.setattr(blueprints_launch, "worktree_root", lambda: "/tmp/wt")
    monkeypatch.setattr(blueprints_peer_member, "_shadow_row", lambda host_key, name: (777, "shadow-uuid"))
    monkeypatch.setattr(run_sessions, "record_launch", lambda store, automation, run_id, index, launched: e.placed.append(launched) or True)
    e.app = FastAPI()
    e.app.include_router(routes.router)
    e.app.dependency_overrides[require_auth] = lambda: None

    async def cancel_run(run_id: str) -> None:
        e.cancelled.append(run_id)

    e.app.state.automation_store = store
    e.app.state.automation_scheduler = SimpleNamespace(cancel_run=cancel_run)
    e.app.include_router(automation_routes.router)
    e.ctx = Context(SimpleNamespace(), store, "boot")
    return e


def member(label: str, host_key: str = None, skills: List[str] = None, prompt: str = None) -> Any:
    return SimpleNamespace(label=label, family="claude", model=None, host_key=host_key, skills=skills or [], opening_prompt=prompt,
                           folder=SimpleNamespace(mode="existing", path=f"/w/{label}"))


def request(env: Env, method: str, path: str, body: Dict[str, Any] = None) -> httpx.Response:
    async def go() -> httpx.Response:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app), base_url="http://t") as client:
            return await client.request(method, path, json=body)

    return asyncio.run(go())


def make(env: Env, target: Dict[str, Any], name: str = "nightly") -> Dict[str, Any]:
    return env.store.create(name=name, cron="0 7 * * *", target=target, enabled=False)


def test_default_is_here_and_auto_is_stored_outside_the_document(env):
    saved = make(env, TARGET)
    aid = saved["automation_id"]
    before = json.dumps(env.store.get(aid), sort_keys=True)
    assert request(env, "GET", f"/automations/{aid}/placement").json() == {"placement": "here", "applies": True}
    put = request(env, "PUT", f"/automations/{aid}/placement", {"placement": "auto"})
    assert put.status_code == 200 and put.json() == {"placement": "auto", "applies": True}
    assert request(env, "GET", f"/automations/{aid}/placement").json()["placement"] == "auto"
    assert env.jobs.automation_placement_get(aid) == "auto"
    assert json.dumps(env.store.get(aid), sort_keys=True) == before
    assert request(env, "PUT", f"/automations/{aid}/placement", {"placement": "elsewhere"}).status_code == 422


def test_an_api_key_cannot_turn_auto_on_for_an_automation(env, monkeypatch):
    from src.api import automation_placement_routes as apr

    aid = make(env, TARGET)["automation_id"]
    monkeypatch.setattr(apr, "is_api_key", lambda token: True)

    async def go() -> httpx.Response:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app), base_url="http://t") as client:
            return await client.put(f"/automations/{aid}/placement", json={"placement": "auto"}, headers={"Authorization": "Bearer cak_x"})

    refused = asyncio.run(go())
    assert refused.status_code == 403 and env.jobs.automation_placement_get(aid) is None


def test_auto_is_refused_for_a_kind_that_stays_here_and_an_unknown_automation_is_404(env, monkeypatch):
    monkeypatch.setitem(targets.RUNNERS, "command", blueprint.run)
    monkeypatch.setitem(targets.VALIDATORS, "command", lambda target: None)
    aid = make(env, COMMAND)["automation_id"]
    assert request(env, "PUT", f"/automations/{aid}/placement", {"placement": "auto"}).status_code == 422
    assert request(env, "GET", f"/automations/{aid}/placement").json() == {"placement": "here", "applies": False}
    assert env.jobs.automation_placement_get(aid) is None
    assert request(env, "GET", "/automations/nope/placement").status_code == 404


def test_deleting_an_automation_drops_its_row(env):
    aid = make(env, TARGET)["automation_id"]
    request(env, "PUT", f"/automations/{aid}/placement", {"placement": "auto"})
    assert env.jobs.automation_placement_get(aid) == "auto"
    assert request(env, "DELETE", f"/automations/{aid}").status_code == 200
    assert env.jobs.automation_placement_get(aid) is None


def _run(env: Env, placement: str) -> m.RunOutcome:
    automation = make(env, TARGET)
    env.jobs.automation_placement_set(automation["automation_id"], placement)
    run = env.store.insert_run(automation["automation_id"], "boot")
    return asyncio.run(blueprint.run(env.ctx, automation, run))


def far(monkeypatch, env: Env, calls: List[str]) -> None:
    async def fake(app, req, starter, body, *, local_create, request_id=None, approved=None):
        calls.append(f"{req.working_dir}|{starter.kind}")
        return PlacedSession({"id": "remote:peer-b:carnivore_x", "session_uuid": "far-uuid", "tmux_session": "carnivore_x",
                              "host_key": "peer-b", "host_label": "tower"}, {"decision": "remote"})

    monkeypatch.setattr(create_mod, "create_placed", fake)


def test_auto_sends_a_hostless_member_to_the_peer_and_an_explicit_computer_wins(env, monkeypatch):
    env.members[:] = [member("a"), member("b", host_key="peer-c"), member("c", skills=["s"])]
    calls: List[str] = []
    far(monkeypatch, env, calls)
    peer_calls: List[str] = []

    async def fake_peer(m_, cols, rows):
        peer_calls.append(m_.label)
        return LaunchedSession(id="remote:peer-c:carnivore_y", tmux_session="carnivore_y", session_uuid="u-c")

    monkeypatch.setattr(blueprints_peer_member, "create_peer_member", fake_peer)
    real_launch = blueprints_launch.launch_member

    async def routing(request, index, member_, *a, **k):
        if member_.host_key:
            return SimpleNamespace(state="launched", problem=None, session=await fake_peer(member_, None, None))
        return await real_launch(request, index, member_, *a, **k)

    monkeypatch.setattr(blueprints_launch, "launch_member", routing)
    out = _run(env, "auto")
    assert out.status == m.RUNNING
    assert calls == ["/w/a|automation"]
    assert peer_calls == ["b"] and env.launched == [2]
    assert [s.id for s in env.placed] == ["remote:peer-b:carnivore_x", "remote:peer-c:carnivore_y", "ses_1"]
    assert env.placed[0].session_row_id == 777 and env.placed[0].session_uuid == "shadow-uuid"


def test_here_never_asks_placement(env, monkeypatch):
    env.members[:] = [member("a")]
    calls: List[str] = []
    far(monkeypatch, env, calls)
    assert _run(env, "here").status == m.RUNNING
    assert calls == [] and env.launched == [0]


def test_a_refused_or_unreadable_placement_starts_the_member_here(env, monkeypatch):
    env.members[:] = [member("a")]

    async def refuse(app, req, starter, body, **kw):
        raise JobError("project_unknown", "no project", 404)

    monkeypatch.setattr(create_mod, "create_placed", refuse)
    assert _run(env, "auto").status == m.RUNNING and env.launched == [0]


def test_a_member_that_stays_here_runs_its_own_local_launch_once(env, monkeypatch):
    env.members[:] = [member("a", prompt="go")]

    async def here(app, req, *, exclude=()):
        return SessionPlacement("here", "this computer has room", project_uid="p1x23456", project_name="app")

    monkeypatch.setattr(decide_mod, "decide", here)
    assert _run(env, "auto").status == m.RUNNING
    assert env.launched == [0] and [s.id for s in env.placed] == ["ses_1"]
