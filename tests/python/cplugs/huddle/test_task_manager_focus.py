
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.core.mcp import tools
from src.core.mcp.caller import AgentCaller
from src.cplugs.host import runtime
from src.cplugs.huddle import routes as huddle_routes, service
from tests.python.cplugs.huddle.test_task_manager_mcp import full_echo
from tests.python.cplugs.owner import turn_on

FOCUS = "/api/v1/cplugs/huddle/focus"
CALLER = AgentCaller("ses_1", "cloude_a", "ses_1")


@pytest.fixture
def setup(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(service, "project_names", lambda ctx: {"12": "carnivore"})
    app = FastAPI()
    app.include_router(huddle_routes.router, prefix="/api/v1")
    host = runtime.install(app, tmp_path)
    published: list[str] = []
    host.publish = published.append
    turn_on(host)
    own = SimpleNamespace(tmux_session=None, label=None, session=SimpleNamespace(id="ses_1"), project_id=12, host_key="local")

    async def infos():
        return [own]

    app.state.session_manager = SimpleNamespace(list_session_infos=infos)
    manager = SimpleNamespace(app=app, gate_waited=True, list_session_infos=infos)
    return SimpleNamespace(app=app, published=published, manager=manager)


@pytest.fixture
def client(setup):
    setup.app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(setup.app) as test_client:
        yield test_client


def add(client, key: str, text: str) -> int:
    return client.post(f"/api/v1/cplugs/huddle/lists/{key}/items", json={"text": text}).json()["id"]


def test_focus_routes_need_auth(setup):
    with TestClient(setup.app) as anonymous:
        assert anonymous.get(FOCUS).status_code in (401, 403)
        assert anonymous.post(FOCUS, json={"clear": True}).status_code in (401, 403)


def test_focus_highlights_live_items_of_the_list_and_pushes(client, setup):
    a, b = add(client, "12", "one"), add(client, "12", "two")
    shared = add(client, "all", "elsewhere")
    setup.published.clear()
    body = client.post(FOCUS, json={"list": "12", "items": [b], "open": a}).json()["focus"]
    assert body["list"] == "12" and body["items"] == [b, a] and body["open"] == a
    assert setup.published == ["cplug.huddle.focus"]
    assert client.get(FOCUS).json()["focus"]["seq"] == body["seq"]
    refused = client.post(FOCUS, json={"list": "12", "items": [a, shared]})
    assert refused.status_code == 404 and str(shared) in refused.json()["detail"]["detail"]
    assert client.post(FOCUS, json={"list": "12", "items": [999]}).status_code == 404
    assert client.post(FOCUS, json={"list": "12", "items": []}).status_code == 400
    assert client.post(FOCUS, json={"items": [a]}).status_code == 400
    assert client.post(FOCUS, json={"list": "77", "items": [a]}).status_code == 404
    assert client.get(FOCUS).json()["focus"]["items"] == [b, a]
    setup.published.clear()
    assert client.post(FOCUS, json={"clear": True}).json() == {"focus": None}
    assert client.get(FOCUS).json() == {"focus": None}
    assert setup.published == ["cplug.huddle.focus"]


def test_a_deleted_item_cannot_be_focused(client):
    gone = add(client, "all", "gone")
    assert client.delete(f"/api/v1/cplugs/huddle/items/{gone}").status_code == 200
    assert client.post(FOCUS, json={"list": "all", "items": [gone]}).status_code == 404


def call(manager, name, args, caller=CALLER, raw=False):
    result = asyncio.run(tools.call_tool(manager, caller, name, args if raw else full_echo(name, args)))
    text = result["content"][0]["text"]
    return (False, text) if result.get("isError") else (True, json.loads(text))


def test_the_mcp_tool_is_declared_and_is_the_same_write(client, setup):
    manifest = json.loads((Path(service.__file__).parent / "cplug.json").read_text())
    assert "huddle_focus" in manifest["surfaces"]["mcp_tools"] and "focus" in manifest["surfaces"]["topics"]
    spec = next(d for d in tools.tool_definitions() if d["name"] == "huddle_focus")
    assert set(spec["inputSchema"]["properties"]) == {"list", "items", "open", "clear", "marker", "cross_project"}
    read_only = {d["name"] for d in tools.tool_definitions(AgentCaller("x", "x", "x", "tok", "read"))}
    assert "huddle_focus" not in read_only

    a, b = add(client, "12", "need your call"), add(client, "12", "waiting on you")
    ok, body = call(setup.manager, "huddle_focus", {"list": "mine", "items": [a, b], "open": a})
    assert ok and body["focus"]["items"] == [a, b] and body["focus"]["open"] == a
    assert client.get(FOCUS).json()["focus"]["items"] == [a, b]
    ok, text = call(setup.manager, "huddle_focus", {"list": "12", "items": [add(client, "all", "shared")]})
    assert not ok and "task_manager_not_found" in text
    shared = add(client, "all", "shared two")
    ok, body = call(setup.manager, "huddle_focus", {"list": "all", "items": [a, shared], "open": shared})
    assert ok and body["focus"]["items"] == [a, shared] and body["focus"]["list"] == "all"
    ok, agg = call(setup.manager, "task_manager_tasks_list", {"aggregate": True})
    flags = {i["id"]: i["unread"] for g in agg["groups"] for i in g["items"]}
    assert flags[a] and flags[shared]
    ok, text = call(setup.manager, "huddle_focus", {"list": "12", "items": [a], "approve": True})
    assert not ok and "unknown argument" in text
    ok, body = call(setup.manager, "huddle_focus", {"clear": True})
    assert ok and body["focus"] is None
    assert client.get(FOCUS).json() == {"focus": None}
