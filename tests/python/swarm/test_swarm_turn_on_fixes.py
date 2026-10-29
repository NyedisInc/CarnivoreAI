
from __future__ import annotations

import asyncio
import os
import tempfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_s2e_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_s2e_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.api.auth import require_auth
from src.core.crosstalk import bus, store as crosstalk_store
from src.core.crosstalk.delivery import dispatcher
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.mcp.caller import AgentCaller
from src.core.swarm import body, create, delivery, effort, project_agent, spawn, store, thread_port, wake_prompt
from src.cplugs.host import runtime
from src.cplugs.huddle import routes as huddle_routes
from src.cplugs.huddle.swarm_port import TaskManagerSwarmPort
from tests.python.cplugs.owner import turn_on

BASE = "/api/v1/cplugs/huddle"


@pytest.fixture()
def world(tmp_path, monkeypatch):
    from src.config import settings

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path, raising=True)
    cfg = tmp_path / "config.json"
    cfg.write_text("{}")
    monkeypatch.setattr(settings, "auth_config_file", str(cfg), raising=False)
    monkeypatch.setattr(settings, "_auth_config_cache", None, raising=False)
    assert ensure_db_migrated(tmp_path).status == "ok"
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        conn.execute("INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, working_dir, title, origin,"
                     " lifecycle, created_at, updated_at) VALUES ('uuid-p', 'cloude', 'cloude_p', 1788821572, ?, 'p agent', 'created',"
                     " 'running', '2026-03-01T00:00:00Z', '2026-09-08T00:00:00Z')", (str(tmp_path),))
        row_id = conn.execute("SELECT id FROM sessions WHERE session_uuid = 'uuid-p'").fetchone()[0]
        boss = store.create_agent(conn, slug="p-agent", rank="project", job="project agent", display_name="p agent", repo_dir=str(tmp_path),
                                  effort="high", naming_state="proposed", naming_family="Volcanoes", persona="Etna")
        store.set_session_row(conn, boss["id"], row_id)
        store.cas_state(conn, boss["id"], "asleep", "awake")
    app = FastAPI()
    app.include_router(huddle_routes.router, prefix="/api/v1")
    host = runtime.install(app, tmp_path)
    host.publish = lambda topic: None
    turn_on(host)
    ctx = host.context("huddle")
    port = TaskManagerSwarmPort(ctx)
    ctx.swarm.register_thread_port(port)
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    pasted = []

    async def deliver_text(app_state, agent_id, text, **kw):
        pasted.append((agent_id, text, kw["source"], kw["authority"]))
        return "delivered"

    monkeypatch.setattr(delivery, "deliver_text", deliver_text)
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, port=port, tmp=tmp_path, cfg=cfg, boss=boss, pasted=pasted, settings=settings, row_id=row_id)
    thread_port.register(None)


def _agent(world):
    with closing(connect(db_path_for(world.tmp), create=False)) as conn:
        return store.get_agent(conn, world.boss["id"])


def test_first_turn_on_sees_the_seeded_profile_without_a_restart(world):
    assert [p.id for p in world.settings.get_launch_profiles()] == []
    assert asyncio.run(body._posture_refusal(_agent(world))) is None
    assert "swarm-upper" in [p.id for p in world.settings.get_launch_profiles()]


def test_naming_approval_reaches_the_agent_and_the_next_spawn_needs_a_name(world, monkeypatch):
    world.cfg.write_text('{"swarm": {"naming_family": true}}')
    item = asyncio.run(world.port.post_card(world.boss["thread_key"], "waiting", "naming family", "x", f"naming:{world.boss['id']}"))
    world.client.patch(f"{BASE}/items/{item}", json={"approved": True})
    assert [i for i in world.client.get(f"{BASE}/lists/{world.boss['thread_key']}").json()["items"]
            if i["id"] == item][0]["status"] == "done"
    approved = _agent(world)
    assert approved["naming_state"] == "approved" and approved["display_name"] == "Etna"
    (agent_id, line, source, authority), = world.pasted
    assert agent_id == approved["id"] and authority == "data" and source == "wake_prompt"
    assert "Volcanoes" in line and "Etna" in line and "swarm_spawn name" in line
    with closing(connect(db_path_for(world.tmp), create=False)) as conn:
        assert conn.execute("SELECT title FROM sessions WHERE id = ?", (world.row_id,)).fetchone()[0] == "Etna"
    assert "Volcanoes" in wake_prompt.render_desk(approved, "manual", "", wake_prompt.desk_mod.Desk(), True)
    assert "Volcanoes" in wake_prompt.resume_message("manual", "", approved, family_on=True)

    async def parent_agent(view, caller):
        return approved

    monkeypatch.setattr(spawn, "parent_agent", parent_agent)
    args = {"job": "add lines", "goal": "do it", "task_type": "lines", "rank": "task"}
    with pytest.raises(spawn.SpawnRefused, match="Volcanoes"):
        asyncio.run(spawn.prepare(object(), AgentCaller("s", "t", "s"), args))
    assert asyncio.run(spawn.prepare(object(), AgentCaller("s", "t", "s"), {**args, "name": "Hekla"})).request["display_name"] == "Hekla"


def test_effort_defaults_to_medium_and_low_is_refused(world, monkeypatch):
    assert effort.resolve(None, None) == ("medium", "")
    assert effort.resolve("high", " because it is wide ") == ("high", "because it is wide")
    for bad, needle in (("low", "Every Swarm agent runs Opus"), ("max", "written reason"), ("high", "effort_reason"), ("xhigh", "effort_reason")):
        with pytest.raises(effort.EffortRefused, match=needle):
            effort.resolve(bad, "")

    async def parent_agent(view, caller):
        return world.boss

    monkeypatch.setattr(spawn, "parent_agent", parent_agent)
    args = {"job": "add lines", "goal": "do it", "task_type": "lines", "rank": "task"}
    plan = asyncio.run(spawn.prepare(object(), AgentCaller("s", "t", "s"), {**args, "name": "Hekla"}))
    assert plan.request["effort"] == "medium" and "Your effort level is medium" in plan.first_message
    with pytest.raises(spawn.SpawnRefused, match="not allowed"):
        asyncio.run(spawn.prepare(object(), AgentCaller("s", "t", "s"), {**args, "effort": "low"}))
    with pytest.raises(create.CreateInvalid, match="Task and feature agents default to medium"):
        asyncio.run(create.create_agent({"repo_dir": str(world.tmp), "job": "j", "rank": "task", "effort": "max"}))


def test_swarm_first_task_carries_no_crosstalk_reply_tail(world, monkeypatch):
    base = {"sender_name": "p", "sender_provider": "claude", "sender_model": None, "thread": "t-1", "id": "m-1", "text": "do the job"}
    assert "crosstalk_reply" not in dispatcher.envelope({**base, "source": "swarm"})
    assert 'crosstalk_reply(message_id="m-1")' in dispatcher.envelope({**base, "source": "crosstalk"})
    sent = []

    async def identities(view, caller, to):
        return {"key": "k-b", "epoch": 1}, {"key": "k-c", "epoch": 1, "id": to}

    async def send(view, caller, **kw):
        sent.append(kw)
        return {"id": "m1"}

    async def make(req):
        return {"id": 99, "slug": "x", "display_name": "X", "rank": "task"}

    async def wake(app_state, agent_id, reason, authority, **kw):
        return None

    async def no_caps(conn, *a):
        return None

    view = SimpleNamespace(app=SimpleNamespace(state=object()), fresh=lambda: view)
    monkeypatch.setattr(create, "create_agent", make)
    monkeypatch.setattr(body, "wake", wake)
    monkeypatch.setattr(bus, "identities", identities)
    monkeypatch.setattr(bus, "send", send)
    monkeypatch.setattr(crosstalk_store, "grant_contact", lambda *a, **kw: None)
    plan = spawn.SpawnPlan(world.boss, {"job": "j", "rank": "task"}, "the first task", None)
    asyncio.run(spawn.run(view, AgentCaller("s", "t", "s"), plan))
    assert sent[0]["source"] == "swarm" and sent[0]["text"] == "the first task"


def test_a_decided_card_leaves_the_send_queue_and_a_woken_agent_clears_its_wake_cards(world):
    key = world.boss["thread_key"]
    status = lambda i: [x for x in world.client.get(f"{BASE}/lists/{key}").json()["items"] if x["id"] == i][0]["status"]
    refused = asyncio.run(world.port.post_card(key, "question", "keep it?", "x", "bogus:1"))
    assert world.client.patch(f"{BASE}/items/{refused}", json={"approved": True}).status_code == 409
    assert status(refused) == "open"
    decided = asyncio.run(world.port.post_card(key, "info", "promotion", "x", "stuck:1:fp"))
    assert world.client.patch(f"{BASE}/items/{decided}", json={"approved": True}).status_code == 200
    assert status(decided) == "done"
    old = asyncio.run(world.port.post_card(key, "info", "wake failed", "x", f"wake_failed:{world.boss['id']}:7"))
    other = asyncio.run(world.port.post_card(key, "info", "wake failed", "x", "wake_failed:99:7"))
    asyncio.run(body._resolve_wake_cards(world.boss["id"]))
    assert status(old) == "done" and status(other) == "open"
