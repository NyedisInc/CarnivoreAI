
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import swarm_switch_routes
from src.api.auth import require_auth
from src.config import settings
from src.core.auto_sleep.sleeper import AutoSleeper
from src.core.mcp import tools
from src.core.mcp.caller import AgentCaller
from src.core.swarm import body, commit, sleep_commit, spawn, switch

pytestmark = [pytest.mark.real_swarm_switch, pytest.mark.real_agent_tool_switches]

PANE = AgentCaller(session_id="ses_a", tmux_name="carnivore_a", current_session_id="ses_a")


@pytest.fixture
def config(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"mcp": {"agent_swarm_tools": True}, "other": {"kept": 1}}))
    monkeypatch.setattr(settings, "auth_config_file", str(path), raising=False)
    settings.drop_auth_config_cache()
    pushed: list = []
    monkeypatch.setattr(switch.resource_push, "notify", lambda topic: pushed.append(topic))
    monkeypatch.setattr("src.core.swarm.push.notify_roster", lambda: None)
    resumed: list = []
    monkeypatch.setattr(switch, "resume", lambda app_state: resumed.append(app_state))
    yield SimpleNamespace(path=path, pushed=pushed, resumed=resumed)
    settings.drop_auth_config_cache()


def _set(enabled: bool) -> dict:
    return asyncio.run(switch.set_enabled(None, enabled))


def test_absent_is_on_and_the_one_writer_round_trips_keeping_siblings(config):
    assert switch.is_on() is True, "a config.json with no swarm_switch block must read ON (Alex's install)"
    assert _set(False) == {"enabled": False} and switch.is_on() is False
    doc = json.loads(config.path.read_text())
    assert doc["swarm_switch"] == {"enabled": False} and doc["other"] == {"kept": 1} and doc["mcp"]["agent_swarm_tools"] is True
    assert config.pushed == ["swarm_switch"] and config.resumed == []
    assert _set(True) == {"enabled": True} and switch.is_on() is True
    assert config.resumed == [None], "turning on resumes what a plugin start does, once"
    _set(True)
    assert config.resumed == [None], "an on that was already on resumes nothing"


def test_a_wake_is_refused_first_with_no_card_and_proceeds_when_on(config, monkeypatch):
    cards: list = []

    async def card(*args, **kwargs):
        cards.append(args)

    async def no_agent(work):
        return None

    monkeypatch.setattr(body, "_card", card)
    monkeypatch.setattr(body, "run_db", no_agent)
    _set(False)
    with pytest.raises(body.SwarmSwitchedOff) as off:
        asyncio.run(body.wake(SimpleNamespace(), 7, "manual", "owner"))
    assert isinstance(off.value, body.BodyError) and str(off.value) == switch.OFF_MESSAGE and cards == []
    _set(True)
    with pytest.raises(body.BodyError) as on:
        asyncio.run(body.wake(SimpleNamespace(), 7, "manual", "owner"))
    assert not isinstance(on.value, body.SwarmSwitchedOff) and "torn down" in str(on.value)


def test_a_spawn_is_refused_before_anything_is_placed(config, monkeypatch):
    placed: list = []

    async def place(plan):
        placed.append(plan)
        raise spawn.SpawnRefused("placed")

    monkeypatch.setattr(spawn, "_place", place)
    plan = spawn.SpawnPlan(parent={"id": 1}, request={}, first_message="go")
    _set(False)
    with pytest.raises(spawn.SpawnRefused, match="the swarm is off"):
        asyncio.run(spawn._start_child(SimpleNamespace(), plan, mint_card=False))
    assert placed == []
    _set(True)
    with pytest.raises(spawn.SpawnRefused, match="placed"):
        asyncio.run(spawn._start_child(SimpleNamespace(), plan, mint_card=False))
    assert placed == [plan]


def test_both_sweeps_are_idle_while_off(config, monkeypatch):
    from src.core.swarm import alerts, closeout, learning, routing
    from src.core.swarm.cards import sweep

    ran: list = []
    for module, name in ((routing, "routing"), (learning, "learning"), (alerts, "alerts"), (closeout, "closeout")):
        monkeypatch.setattr(module, "sweep", lambda app_state, _n=name: _record(ran, _n))
    monkeypatch.setattr(sweep, "run", lambda app_state: _record(ran, "cards"))
    sleeper = SimpleNamespace(_app_state=None)
    _set(False)
    asyncio.run(AutoSleeper._route_questions(sleeper))
    asyncio.run(AutoSleeper._card_sweep(sleeper))
    assert ran == []
    _set(True)
    asyncio.run(AutoSleeper._route_questions(sleeper))
    asyncio.run(AutoSleeper._card_sweep(sleeper))
    assert ran == ["routing", "learning", "alerts", "closeout", "cards"]


async def _record(ran: list, name: str) -> None:
    ran.append(name)


def test_a_sleep_commits_nothing_while_off(config, monkeypatch):
    committed: list = []

    async def run_db(work):
        return work(None)

    def commit_memory(conn, agent, message=""):
        committed.append(agent["id"])
        return commit.CommitResult(status="committed", sha="abc")

    monkeypatch.setattr(body, "run_db", run_db)
    monkeypatch.setattr(commit, "commit_memory", commit_memory)
    agent = {"id": 3, "repo_dir": "/nowhere"}
    _set(False)
    assert asyncio.run(sleep_commit.run(agent)) is None and committed == []
    _set(True)
    assert asyncio.run(sleep_commit.run(agent))["sha"] == "abc" and committed == [3]


def test_swarm_tools_hide_with_the_switch_sentence_while_its_own_tools_stay(config):
    def listed() -> set:
        return {d["name"] for d in tools.tool_definitions(PANE)}

    assert {"swarm_roster", "swarm_switch_status", "swarm_switch_off", "swarm_switch_on"} <= listed()
    _set(False)
    names = listed()
    assert "swarm_roster" not in names and not any(n.startswith("swarm_") and "switch" not in n for n in names)
    assert {"swarm_switch_status", "swarm_switch_off", "swarm_switch_on"} <= names
    refused = asyncio.run(tools.call_tool(SimpleNamespace(), PANE, "swarm_roster", {}))
    assert refused["isError"] is True and "turned the swarm off" in refused["content"][0]["text"]
    _set(True)
    assert "swarm_roster" in listed()


def test_the_route_needs_auth_and_round_trips(config):
    app = FastAPI()
    app.include_router(swarm_switch_routes.router)
    client = TestClient(app)
    assert client.get("/swarm/switch").status_code in (401, 403)
    assert client.put("/swarm/switch", json={"enabled": False}).status_code in (401, 403)
    assert switch.is_on() is True, "an unauthenticated write changed nothing"
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    assert client.get("/swarm/switch").json() == {"enabled": True}
    assert client.put("/swarm/switch", json={"enabled": False}).json() == {"enabled": False}
    assert client.get("/swarm/switch").json() == {"enabled": False}
    assert client.put("/swarm/switch", json={"enabled": "maybe"}).status_code == 422
    assert client.put("/swarm/switch", json={"enabled": True, "extra": 1}).status_code == 422
    with pytest.raises(Exception) as gate:
        swarm_switch_routes.require_swarm_on()
    assert getattr(gate.value, "status_code", None) == 409 and gate.value.detail["code"] == "swarm_off"
    assert client.put("/swarm/switch", json={"enabled": True}).json() == {"enabled": True}
    swarm_switch_routes.require_swarm_on()


def test_the_mcp_off_tool_runs_at_once_and_the_on_tool_waits(config, monkeypatch):
    from src.core.mcp import beast_mode, pending

    monkeypatch.setattr(pending, "_store", pending.PendingActions())
    monkeypatch.setattr(pending, "MAX_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(beast_mode, "beast_enabled", lambda: True)
    manager = SimpleNamespace(app=SimpleNamespace(state=None))
    assert asyncio.run(tools.call_tool(manager, PANE, "swarm_switch_off", {"enabled": True}))["isError"] is True
    off = asyncio.run(tools.call_tool(manager, PANE, "swarm_switch_off", {}))
    assert not off.get("isError") and switch.is_on() is False
    status = asyncio.run(tools.call_tool(manager, PANE, "swarm_switch_status", {}))
    assert json.loads(status["content"][0]["text"])["enabled"] is False
    on = asyncio.run(tools.call_tool(manager, PANE, "swarm_switch_on", {}))
    assert "pending" in on["content"][0]["text"] and switch.is_on() is False, "turning the Swarm on waits for the owner"
