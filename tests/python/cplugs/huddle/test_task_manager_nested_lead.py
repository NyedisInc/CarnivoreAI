
from __future__ import annotations

import asyncio

import pytest

from src.cplugs.host import capabilities, runtime
from src.cplugs.huddle import service
from src.cplugs.huddle.roles import gone, lead, port as roles_port, retrofit
from src.cplugs.huddle.roles.store import RoleStore
from tests.python.cplugs.huddle.roles_rig import BASE, SwarmStub, aged, give_asleep, give_rows, use_swarm
from tests.python.cplugs.huddle.test_task_manager_routes import app, client  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_tags import store_of

URL = f"{BASE}/lists/12/lead"


@pytest.fixture
def world(app, monkeypatch):
    monkeypatch.setattr(service, "project_names", lambda ctx: {"10": "Mac", "11": "Harbor", "12": "Harbor Docker", "20": "Other"})
    monkeypatch.setattr(capabilities.Projects, "enclosing", lambda self: {"12": ["11", "10"], "11": ["10"]})
    give_asleep(monkeypatch, [])
    give_rows(app, [aged("ses_fleet", 11, 5), aged("ses_other", 20, 5), aged("ses_dock", 12, 1)])
    return use_swarm(monkeypatch, SwarmStub(project_agents={"11": "ses_fleet", "20": "ses_other"}))


def test_the_enclosing_projects_agent_is_accepted_as_the_nested_projects_lead(client, world):
    answer = client.put(URL, json={"session": "ses_fleet"})
    assert answer.status_code == 200
    body = answer.json()
    assert (body["seat"]["session"], body["agent"], world.promoted) == ("ses_fleet", False, [])


def test_the_nearest_enclosing_project_with_an_agent_is_the_one_that_counts(client, world):
    world.project_agents["10"] = "ses_mac"
    world.agent_projects.add("10")
    assert client.put(URL, json={"session": "ses_mac"}).status_code == 400
    assert client.put(URL, json={"session": "ses_fleet"}).status_code == 200
    world.project_agents.pop("11")
    world.agent_projects.discard("11")
    assert client.put(URL, json={"session": "ses_mac"}).status_code == 200


def test_an_unrelated_projects_agent_is_still_refused(client, world):
    refused = client.put(URL, json={"session": "ses_other"})
    assert refused.status_code == 400 and "cannot lead" in refused.json()["detail"]["detail"]
    assert RoleStore(store_of(client.app)).seat("12").lead_key == ""


def test_a_nested_project_with_its_own_agent_does_not_take_the_enclosing_one(client, world):
    world.project_agents["12"] = "ses_dock"
    world.agent_projects.add("12")
    assert client.put(URL, json={"session": "ses_fleet"}).status_code == 400


@pytest.fixture
def ctx(app, world):
    context = runtime.host_for(app).context("huddle", background=True)
    roles_port.register(context)
    yield context
    roles_port.unregister()


def test_the_enclosing_agent_seat_is_not_gone_and_loses_that_only_when_the_nesting_goes(app, client, ctx, monkeypatch):
    assert client.put(URL, json={"session": "ses_fleet"}).status_code == 200
    assert asyncio.run(gone.check(ctx)) == []
    assert client.get(f"{BASE}/roles").json()["leads"]["12"]["session"] == "ses_fleet"
    assert "vacant_reason" not in client.get(f"{BASE}/roles").json()["leads"]["12"]
    monkeypatch.setattr(capabilities.Projects, "enclosing", lambda self: {})
    assert [a["list"] for a in asyncio.run(gone.check(ctx))] == ["12"]


def test_the_retrofit_reports_already_agent_for_a_nested_project_the_enclosing_agent_leads(client, world):
    before = {r["project"]: r for r in client.get(f"{BASE}/leads/retrofit").json()["plan"]}["Harbor Docker"]
    assert before["action"] == retrofit.PROMOTE and before["session"] == "ses_dock"
    client.put(URL, json={"session": "ses_fleet"})
    after = {r["project"]: r for r in client.get(f"{BASE}/leads/retrofit").json()["plan"]}["Harbor Docker"]
    assert after["action"] == retrofit.ALREADY_AGENT and "session" not in after
    assert lead.BY_OWNER == RoleStore(store_of(client.app)).seat("12").lead_by
