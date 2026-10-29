
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from src.core.mcp import tools
from src.core.mcp.caller import AgentCaller
from src.cplugs.huddle import mcp
from src.cplugs.huddle.roles import mcp_roles
from src.cplugs.sdk import ToolError
from src.cplugs.host import runtime
from src.cplugs.huddle.roles import port as roles_port, service as roles_service
from tests.python.cplugs.huddle.roles_rig import BASE, SwarmStub, aged, give_asleep, give_rows, use_swarm
from tests.python.cplugs.huddle.test_task_manager_routes import app, client  # noqa: F401

OLD = AgentCaller("ses_old", "cloude_old", "ses_old")
NEW = AgentCaller("ses_new", "cloude_new", "ses_new")


@pytest.fixture
def two(app, monkeypatch):
    give_asleep(monkeypatch, [])
    give_rows(app, [aged("ses_old", 12, 5), aged("ses_new", 12, 1)])
    roles_port.register(runtime.host_for(app).context("huddle", background=True))
    yield app
    roles_port.unregister()


def run(app, name: str, args: dict, caller: AgentCaller = OLD):
    result = asyncio.run(tools.call_tool(app.state.session_manager, caller, name, args))
    text = result["content"][0]["text"]
    return (False, text) if result.get("isError") else (True, json.loads(text))


def test_the_roles_routes_need_auth(app):
    with TestClient(app) as anonymous:
        for method, path, body in [("get", f"{BASE}/roles", None), ("put", f"{BASE}/lists/12/lead", {"session": None}),
                                   ("put", f"{BASE}/sessions/x/dnd", {"dnd": True})]:
            assert anonymous.request(method, path, json=body).status_code in (401, 403), path


def test_reading_the_roles_seats_the_first_session_and_shows_the_seat(client, two):
    roles = client.get(f"{BASE}/roles").json()
    assert roles["leads"]["12"]["session"] == "ses_old" and roles["leads"]["12"]["by"] == "auto" and roles["dnd"] == []


def test_the_owner_sets_clears_and_refuses_a_lead(client, two):
    seat = client.put(f"{BASE}/lists/12/lead", json={"session": "ses_new"}).json()["seat"]
    assert seat["session"] == "ses_new" and seat["by"] == "owner"
    assert client.get(f"{BASE}/session-prefs").json()["leads"] == {"12": "ses_new"}
    assert client.put(f"{BASE}/lists/12/lead", json={"session": None}).json()["seat"]["session"] is None
    assert client.put(f"{BASE}/lists/12/lead", json={"session": "ses_other"}).status_code == 400
    assert client.put(f"{BASE}/lists/12/lead", json={"session": "bad key!"}).status_code == 400
    assert client.put(f"{BASE}/lists/all/lead", json={"session": "ses_new"}).status_code == 400
    assert client.put(f"{BASE}/lists/12/lead", json={}).status_code == 422
    assert client.put(f"{BASE}/lists/77/lead", json={"session": None}).status_code == 404


def test_a_swarm_body_cannot_be_made_lead_by_the_owner(client, two, monkeypatch):
    use_swarm(monkeypatch, SwarmStub(bodies={"ses_new"}))
    assert client.put(f"{BASE}/lists/12/lead", json={"session": "ses_new"}).status_code == 400


def test_dnd_route_writes_reads_and_announces(client, two, monkeypatch):
    announced = []
    monkeypatch.setattr(roles_service, "notify_prefs", lambda ctx: announced.append("prefs"))
    assert client.put(f"{BASE}/sessions/ses_new/dnd", json={"dnd": True}).json() == {"session": "ses_new", "dnd": True}
    assert client.get(f"{BASE}/roles").json()["dnd"] == ["ses_new"] and client.get(f"{BASE}/session-prefs").json()["dnd"] == ["ses_new"]
    assert client.put(f"{BASE}/sessions/ses_new/dnd", json={"dnd": "yes"}).status_code == 422
    assert client.put(f"{BASE}/sessions/bad key!/dnd", json={"dnd": True}).status_code in (400, 404)
    assert announced == ["prefs"]


def test_a_session_sets_its_own_dnd_and_clears_it(client, two):
    assert run(two, "task_manager_role_set", {"role": "dnd", "on": True})[1] == {"role": "dnd", "on": True, "guide_rev": mcp.TASK_MANAGER_GUIDE_REV}
    assert client.get(f"{BASE}/roles").json()["dnd"] == ["ses_old"]
    run(two, "task_manager_role_set", {"role": "dnd", "on": False})
    assert client.get(f"{BASE}/roles").json()["dnd"] == []


def test_a_session_takes_the_seat_only_while_it_is_vacant_and_is_told_who_holds_it(client, two):
    client.put(f"{BASE}/lists/12/lead", json={"session": None})
    ok, took = run(two, "task_manager_role_set", {"role": "lead", "on": True}, NEW)
    assert ok, took
    assert took["lead"]["session"] == "ses_new" and took["lead"]["by"] == "session" and took["list"] == "12"
    ok, refused = run(two, "task_manager_role_set", {"role": "lead", "on": True}, OLD)
    assert not ok and "ses_new" in refused and "ask the owner" in refused
    ok, again = run(two, "task_manager_role_set", {"role": "lead", "on": True}, NEW)
    assert ok and again["lead"]["session"] == "ses_new"
    ok, not_mine = run(two, "task_manager_role_set", {"role": "lead", "on": False}, OLD)
    assert not ok and "do not hold" in not_mine
    ok, given_up = run(two, "task_manager_role_set", {"role": "lead", "on": False}, NEW)
    assert ok and given_up["lead"]["session"] is None
    assert client.get(f"{BASE}/roles").json()["leads"]["12"]["session"] is None
    assert run(two, "task_manager_role_set", {"role": "lead", "on": True}, OLD)[0]


def test_the_tool_refuses_bad_arguments_an_external_token_and_a_swarm_body(client, two, monkeypatch):
    assert not run(two, "task_manager_role_set", {"role": "boss", "on": True})[0]
    assert not run(two, "task_manager_role_set", {"role": "dnd", "on": "yes"})[0]
    assert "unknown argument" in run(two, "task_manager_role_set", {"role": "dnd", "on": True, "session": "x"})[1]
    external = AgentCaller("mcp-token:1", "mcp-token:1", "mcp-token:1", "tok", "write")
    with pytest.raises(ToolError, match="external token"):
        asyncio.run(mcp_roles.role_set(runtime.host_for(two).context("huddle"), external, {"role": "dnd", "on": True}, caller_key=lambda: None))
    use_swarm(monkeypatch, SwarmStub(bodies={"ses_new"}))
    ok, text = run(two, "task_manager_role_set", {"role": "lead", "on": True}, NEW)
    assert not ok and "swarm agent cannot" in text


def test_huddle_list_on_a_project_carries_who_leads_and_what_you_are(client, two):
    client.put(f"{BASE}/lists/12/lead", json={"session": "ses_new"})
    run(two, "task_manager_role_set", {"role": "dnd", "on": True}, OLD)
    ok, listed = run(two, "task_manager_tasks_list", {"list": "12"}, NEW)
    assert ok and listed["roles"] == {"lead": {"session": "ses_new", "name": "ses_new"}, "you": {"lead": True, "dnd": False}}
    ok, other = run(two, "task_manager_tasks_list", {"list": "12"}, OLD)
    assert other["roles"]["you"] == {"lead": False, "dnd": True}
    assert "roles" not in run(two, "task_manager_tasks_list", {"list": "all"})[1]


def test_a_lead_session_is_refused_do_not_disturb_and_taking_the_seat_clears_its_own(client, two):
    run(two, "task_manager_role_set", {"role": "dnd", "on": True}, NEW)
    ok, taken = run(two, "task_manager_role_set", {"role": "lead", "on": True}, NEW)
    assert ok and taken["lead"]["session"] == "ses_new"
    assert client.get(f"{BASE}/roles").json()["dnd"] == []
    ok, text = run(two, "task_manager_role_set", {"role": "dnd", "on": True}, NEW)
    assert not ok and "cannot go on do not disturb" in text


def test_the_tool_is_in_the_manifest_and_the_agent_write_class():
    from src.cplugs.huddle import mcp as tool_module

    assert "task_manager_role_set" in json.loads(open(tool_module.__file__.replace("mcp.py", "cplug.json")).read())["surfaces"]["mcp_tools"]
    assert tool_module.TOOLS["task_manager_role_set"].gate == "agent"
