
from __future__ import annotations

import asyncio
import json
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.core.db import connect, db_path_for
from src.core.db_steps import run_chain
from src.core.mcp import tools
from src.core.mcp.caller import AgentCaller
from src.core.swarm import store as swarm_store, thread_port
from src.cplugs.host import runtime
from src.cplugs.huddle import rules, routes as huddle_routes, service
from src.cplugs.huddle.swarm_port import TaskManagerSwarmPort
from tests.python.cplugs.owner import turn_on

BASE = "/api/v1/cplugs/huddle"
CALLER = AgentCaller("ses_1", "cloude_a", "ses_1")


@pytest.fixture
def world(tmp_path: Path, monkeypatch):
    with closing(connect(db_path_for(tmp_path))) as conn:
        run_chain(conn, 0, 59)
        alpha = swarm_store.create_agent(conn, slug="alpha", rank="alpha", job="j", display_name="Alpha",
                                        repo_dir=str(tmp_path), effort="high")
        feature = swarm_store.create_agent(conn, slug="loki", rank="feature", job="j", display_name="Loki",
                                          repo_dir=str(tmp_path), effort="high", parent_id=alpha["id"])
    app = FastAPI()
    app.include_router(huddle_routes.router, prefix="/api/v1")
    host = runtime.install(app, tmp_path)
    host.publish = lambda topic: None
    turn_on(host)
    monkeypatch.setattr(type(host.context("huddle").projects), "list", lambda self: [{"id": 12, "name": "carnivore"}])
    pane = SimpleNamespace(session=SimpleNamespace(id="ses_1", agent_type="claude", last_activity=None), agent_type="claude",
                           agent_family=None, project_id=12, project_name="carnivore", label="a", tmux_session="cloude_a",
                           activity_status="idle", host_key="local")

    async def infos():
        return [pane]

    manager = SimpleNamespace(app=app, gate_waited=True, list_session_infos=infos)
    app.state.session_manager = manager
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, manager=manager, host=host, key=f"agent:{feature['id']}")
    thread_port.register(None)


def test_agent_list_reads_names_from_swarm_and_stores_author_keys(world):
    client, key = world.client, world.key
    assert rules.check_list_key(key) == key and rules.agent_id_of(key) and rules.agent_id_of("12") is None

    lists = client.get(f"{BASE}/lists").json()["lists"]
    by_key = {row["key"]: row for row in lists}
    assert by_key[key]["name"] == "Loki" and by_key[key]["project_id"] is None
    assert by_key["12"]["project_id"] == 12 and by_key["all"]["name"] is None

    added = client.post(f"{BASE}/lists/{key}/items", json={"text": "agent item"})
    assert added.status_code == 200 and added.json()["created_key"] == "owner"
    assert client.post(f"{BASE}/lists/agent:999/items", json={"text": "x"}).status_code == 404
    assert client.post(f"{BASE}/lists/agent:x/items", json={"text": "x"}).status_code == 400

    groups = client.get(f"{BASE}/aggregate", params={"include_swarm": "1"}).json()["groups"]
    assert [(g["list"], g["name"], g["project_id"]) for g in groups] == [(key, "Loki", None)]
    assert client.get(f"{BASE}/aggregate").json()["groups"] == []
    assert client.get(f"{BASE}/lists/{key}").status_code == 200

    item_id = added.json()["id"]
    posted = client.post(f"{BASE}/items/{item_id}/messages", json={"text": "hi"}).json()
    assert posted["message"]["author_key"] == "owner"

    ask = asyncio.run(tools.call_tool(world.manager, CALLER, "task_manager_ask", {"list": key, "item": item_id, "text": "which?", "lean": False}))
    assert not ask.get("isError"), ask
    thread = client.get(f"{BASE}/lists/{key}").json()["items"][0]["thread"]
    assert [(m["author"], m["author_key"]) for m in thread] == [("joe", "owner"), ("claude", "ses_1")]

    add = asyncio.run(tools.call_tool(world.manager, CALLER, "task_manager_add", {"list": key, "text": "from the pane", "lean": False}))
    assert json.loads(add["content"][0]["text"])["id"]
    created = {i["text"]: i["created_key"] for i in client.get(f"{BASE}/lists/{key}").json()["items"]}
    assert created == {"agent item": "owner", "from the pane": "ses_1"}


def test_thread_port_posts_cards_and_owner_messages(world):
    ctx = world.host.context("huddle")
    port = TaskManagerSwarmPort(ctx)
    ctx.swarm.register_thread_port(port)
    assert thread_port.get().inner is port

    async def run():
        card = await port.post_card(world.key, "question", "ship it?", "ready to ship", "card:1")
        ref = await port.post_owner_message(world.key, "go")
        await port.close_card(card, "done")
        return card, ref

    card, ref = asyncio.run(run())
    items = {i["id"]: i for i in world.client.get(f"{BASE}/lists/{world.key}").json()["items"]}
    assert items[card]["created_key"] == "swarm" and items[card]["swarm_ref"] == "card:1" and items[card]["state"] == "done"
    chat = next(i for i in items.values() if i["swarm_ref"] == "chat")
    assert ref == f"huddle:msg:{chat['thread'][0]['id']}" and chat["thread"][0]["author_key"] == "owner"

    entries = asyncio.run(port.read_thread(world.key, 10))
    assert {(e["kind"], e.get("card"), e.get("text")) for e in entries} == {("card", "question", None), ("owner", None, "go")}
    assert [e["at"] for e in entries] == sorted(e["at"] for e in entries)
    assert len(asyncio.run(port.read_thread(world.key, 1))) == 1


def test_repeat_wake_refusal_keeps_one_open_card_with_a_rising_count(world):
    port = TaskManagerSwarmPort(world.host.context("huddle"))

    async def run():
        ids = [await port.post_card(world.key, "info", "cannot wake yet", "Loki stays asleep: pegged.", "wake_refused:3") for _ in range(3)]
        other = await port.post_card(world.key, "info", "cannot wake: project moved away", "Loki stays asleep: moved.", "wake_refused:3")
        return ids, other

    ids, other = asyncio.run(run())
    assert len(set(ids)) == 1 and other != ids[0]
    items = {i["id"]: i for i in world.client.get(f"{BASE}/lists/{world.key}").json()["items"]}
    assert "refused 3 times, last at" in items[ids[0]]["text"] and items[ids[0]]["text"].startswith("Loki stays asleep: pegged.")
    assert len([i for i in items.values() if i["swarm_ref"] == "wake_refused:3"]) == 2


def test_system_closed_card_is_marked_closed_never_a_decision(world):
    ctx = world.host.context("huddle")
    port = TaskManagerSwarmPort(ctx)

    async def run():
        open_card = await port.post_card(world.key, "question", "trust this folder?", "trust it", "trust:4:ab")
        decided = await port.post_card(world.key, "question", "other", "other", "import:4:cd")
        await port.close_open_cards(world.key, "trust:")
        await port.close_open_cards(world.key, "trust:")
        return open_card, decided

    open_card, decided = asyncio.run(run())
    items = {i["id"]: i for i in world.client.get(f"{BASE}/lists/{world.key}").json()["items"]}
    assert (items[open_card]["swarm_ref"], items[open_card]["state"]) == (rules.CLOSED_REF_PREFIX + "trust:4:ab", "done")
    assert (items[decided]["swarm_ref"], items[decided]["state"]) != (rules.CLOSED_REF_PREFIX + "import:4:cd", "done")
