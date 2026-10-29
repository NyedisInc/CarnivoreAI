
from __future__ import annotations

import asyncio
import json
from contextlib import closing
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from tests.python.swarm.test_swarm_s7_smokefix import _db, env  # noqa: F401,E402
from src.api import swarm_routes
from src.api.auth import require_auth
from src.core.db import connect, db_path_for
from src.core.swarm import body_create, definition, leaders, memory, store


async def _noop(*args, **kwargs):
    return []


@pytest.fixture()
def app(env):  # noqa: F811
    for name in ("close_open_cards", "open_cards", "read_thread", "archive_thread"):
        setattr(env.port, name, _noop)

    class Manager:
        async def list_session_infos(self):
            return []

    with closing(connect(db_path_for(env.state), create=False)) as conn:
        folder = env.root / "Plain"
        folder.mkdir()
        body_create.ensure_repo(str(folder))
        project = body_create.register_project(conn, str(folder), "Plain")
        conn.execute("INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, working_dir, title, origin, lifecycle,"
                     " created_at, updated_at) VALUES ('uuid-plain', 'cloude', 'cloude_plain', 1788821573, ?, 't', 'created', 'running',"
                     " '2026-03-01T00:00:00Z', '2026-09-08T00:00:00Z')", (str(folder),))
        row = conn.execute("SELECT id FROM sessions WHERE session_uuid = 'uuid-plain'").fetchone()[0]
        agent = store.create_agent(conn, slug="plain-agent", rank="project", job="j", display_name="Plain agent", repo_dir=str(folder),
                                   effort="high", project_id=project["id"], parent_id=env.agents["acmeboss"]["id"])
        store.set_session_row(conn, agent["id"], row)
        env.plain = store.get_agent(conn, agent["id"])
        feature = store.create_agent(conn, slug="feat", rank="feature", job="j", display_name="Feat", repo_dir=str(folder), effort="high")
        env.feature = feature
    api = FastAPI()
    api.include_router(swarm_routes.router, prefix="/api/v1")
    api.dependency_overrides[require_auth] = lambda: None
    api.state.session_manager = Manager()
    return api


def _client(api):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://t/api/v1")


@pytest.mark.asyncio
async def test_turn_off_of_a_leader_needs_its_exact_name_and_rename_persists(env, app):  # noqa: F811
    plain = env.plain
    async with _client(app) as c:
        refused = await c.post(f"/swarm/agents/{plain['id']}/turn-off")
        assert refused.status_code == 409 and refused.json()["detail"]["code"] == "leader_protected"
        assert refused.json()["detail"]["name"] == "Plain" and refused.json()["detail"]["rank"] == "project"
        wrong = await c.post(f"/swarm/agents/{plain['id']}/turn-off", json={"confirm_name": "plain agent"})
        assert wrong.status_code == 409 and wrong.json()["detail"]["code"] == "leader_protected"
        assert _db(env, lambda cn: store.get_agent(cn, plain["id"]))["torn_down_at"] is None
        alpha = await c.post(f"/swarm/agents/{env.agents['alpha']['id']}/turn-off", json={"confirm_name": "Alpha"})
        assert alpha.status_code == 409 and alpha.json()["detail"]["code"] == "swarm_refused"
        mem = memory.memory_dir(env.root / "Plain", "plain-agent", "project")
        mem.mkdir(parents=True)
        (mem / "swarm.json").write_text(definition.render_swarm_json(definition.SwarmMeta(
            slug="plain-agent", display_name="Plain agent", rank="project", parent_slug=None, persona="", naming_family="", character_seed="1")))
        renamed = await c.put(f"/swarm/agents/{plain['id']}/name", json={"display_name": "  Wolfpack Lead  "})
        assert renamed.status_code == 200 and renamed.json()["display_name"] == "Wolfpack Lead"
        row = _db(env, lambda cn: store.get_agent(cn, plain["id"]))
        assert row["display_name"] == "Wolfpack Lead" and row["slug"] == "plain-agent"
        assert json.loads((mem / "swarm.json").read_text())["display_name"] == "Wolfpack Lead"
        label = _db(env, lambda cn: cn.execute("SELECT title FROM sessions WHERE session_uuid = 'uuid-plain'").fetchone()[0])
        assert label == "Wolfpack Lead"
        assert (await c.post(f"/swarm/agents/{plain['id']}/turn-off", json={"confirm_name": "Plain agent"})).status_code == 409
        done = await c.post(f"/swarm/agents/{plain['id']}/turn-off", json={"confirm_name": "Wolfpack Lead"})
        assert done.status_code == 200 and done.json()["state"] == "torn_down"
        assert (await c.put(f"/swarm/agents/{env.feature['id']}/name", json={"display_name": "fix: nope"})).status_code == 422
        assert (await c.put(f"/swarm/agents/{env.agents['alpha']['id']}/name", json={"display_name": "   "})).status_code == 422
        assert (await c.put("/swarm/agents/99999/name", json={"display_name": "X"})).status_code == 404
        assert (await c.put(f"/swarm/agents/{env.agents['alpha']['id']}/name", json={"display_name": "Chief"})).json()["display_name"] == "Chief"


def test_the_session_guard_refuses_a_leader_without_its_name_and_lets_a_plain_session_through(env, app):  # noqa: F811
    boss = env.agents["acmeboss"]
    for kw in ({"session_uuid": "uuid-acmeboss"}, {"tmux_name": "cloude_acmeboss"}):
        with pytest.raises(HTTPException) as err:
            asyncio.run(leaders.require_confirm(confirm_name=None, **kw))
        assert err.value.status_code == 409 and err.value.detail["code"] == "leader_protected" and err.value.detail["name"] == boss["display_name"]
        with pytest.raises(HTTPException):
            asyncio.run(leaders.require_confirm(confirm_name="acmeboss", **kw))
        asyncio.run(leaders.require_confirm(confirm_name=boss["display_name"], **kw))
    asyncio.run(leaders.require_confirm(session_uuid="uuid-some-other", tmux_name="cloude_other", confirm_name=None))


def test_the_agents_tab_rename_of_a_leaders_body_carries_onto_the_agent_name(env, app):  # noqa: F811
    asyncio.run(leaders.follow_session_rename("cloude_plain", "Swarm Lead"))
    assert _db(env, lambda cn: store.get_agent(cn, env.plain["id"]))["display_name"] == "Swarm Lead"
    asyncio.run(leaders.follow_session_rename("cloude_not_a_leader", "Whatever"))
    assert _db(env, lambda cn: store.get_agent(cn, env.plain["id"]))["display_name"] == "Swarm Lead"


@pytest.mark.asyncio
async def test_the_owner_rename_of_an_awake_leader_tells_every_browser(env, app, monkeypatch):  # noqa: F811
    sent = []

    real_detail = swarm_routes.views.detail

    async def awake_detail(manager, agent_id):
        return {**await real_detail(manager, agent_id), "session_id": "ses_plain"}

    monkeypatch.setattr(swarm_routes.views, "detail", awake_detail)
    monkeypatch.setattr(swarm_routes.session_change_notice, "publish", lambda state, frame: sent.append(frame))
    async with _client(app) as c:
        assert (await c.put(f"/swarm/agents/{env.plain['id']}/name", json={"display_name": "Wolf Lead"})).status_code == 200
    assert len(sent) == 1 and sent[0]["session_id"] == "ses_plain" and sent[0]["new_name"] == "Wolf Lead"
