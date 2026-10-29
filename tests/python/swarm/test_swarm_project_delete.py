
from __future__ import annotations

import asyncio
from contextlib import closing
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from tests.python.swarm.test_swarm_s7_smokefix import _db, env  # noqa: F401,E402
from src.api import projects_routes
from src.core.db import connect, db_path_for
from src.core.swarm import body, body_create, routing, store, thread_port
from tests.python.swarm.test_swarm_turn_off import CardPort


def _make(env, name):  # noqa: F811
    with closing(connect(db_path_for(env.state), create=False)) as conn:
        folder = env.root / name
        folder.mkdir()
        body_create.ensure_repo(str(folder))
        project = body_create.register_project(conn, str(folder), name)
        conn.execute("UPDATE projects SET company_id = ? WHERE id = ?", (env.acme["id"], project["id"]))
        conn.commit()
        lead = store.create_agent(conn, slug=f"{name.lower()}-agent", rank="project", job="j", display_name=f"{name} agent",
                                  repo_dir=str(folder), effort="high", project_id=project["id"], parent_id=env.agents["acmeboss"]["id"])
        kid = store.create_agent(conn, slug=f"{name.lower()}-feat", rank="feature", job="j", display_name=f"{name} feat",
                                 repo_dir=str(folder), effort="medium", parent_id=lead["id"])
    for agent in (lead, kid):
        _db(env, lambda c, a=agent: store.cas_state(c, a["id"], "asleep", "awake"))
    thread_port.register(CardPort())
    return project, lead, kid, folder


def _app():
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))


def test_delete_turns_off_the_agents_leaves_first_deletes_the_row_and_tells_the_company(env, monkeypatch):  # noqa: F811
    project, lead, kid, folder = _make(env, "Doomed")
    slept, told = [], []

    async def sleep(app_state, agent_id, reason="sleep"):
        slept.append(agent_id)
        _db(env, lambda c: store.cas_state(c, agent_id, "awake", "asleep"))
        return SimpleNamespace(state="asleep", commit={"status": "committed", "sha": "abc"})

    async def tell(app_state, agent_id, text, **kw):
        told.append((agent_id, text))
        return True

    monkeypatch.setattr(body, "sleep", sleep)
    monkeypatch.setattr(routing, "tell", tell)
    asyncio.run(projects_routes.delete_project("Doomed", _app()))
    assert slept == [kid["id"], lead["id"]]
    for agent in (lead, kid):
        assert _db(env, lambda c, a=agent: store.get_agent(c, a["id"]))["torn_down_at"] is not None
    assert _db(env, lambda c: c.execute("SELECT 1 FROM projects WHERE id = ?", (project["id"],)).fetchone()) is None
    assert told and told[0][0] == env.agents["acmeboss"]["id"] and "Doomed" in told[0][1] and "gone for good" in told[0][1]
    assert folder.is_dir()


def test_a_refused_turn_off_keeps_the_project_and_tells_nobody(env, monkeypatch):  # noqa: F811
    project, lead, _kid, _folder = _make(env, "Stubborn")
    told = []

    async def sleep(app_state, agent_id, reason="sleep"):
        raise body.BodyError("the body would not close")

    async def tell(app_state, agent_id, text, **kw):
        told.append(agent_id)
        return True

    monkeypatch.setattr(body, "sleep", sleep)
    monkeypatch.setattr(routing, "tell", tell)
    with pytest.raises(HTTPException) as raised:
        asyncio.run(projects_routes.delete_project("Stubborn", _app()))
    assert raised.value.status_code == 409 and raised.value.detail["code"] == "swarm_refused"
    assert _db(env, lambda c: c.execute("SELECT 1 FROM projects WHERE id = ?", (project["id"],)).fetchone()) is not None
    assert _db(env, lambda c: store.get_agent(c, lead["id"]))["torn_down_at"] is None and told == []
