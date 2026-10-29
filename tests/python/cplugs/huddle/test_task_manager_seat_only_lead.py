
from __future__ import annotations

import asyncio

import pytest

from src.cplugs.host import runtime
from src.cplugs.huddle import service
from src.cplugs.huddle.roles import gone, lead, mcp_lead, port as roles_port, retrofit
from src.cplugs.huddle.roles.store import RoleStore
from src.cplugs.sdk import ToolError
from src.cplugs.sdk.session_rows import StoredRow
from tests.python.cplugs.huddle.roles_rig import BASE, SwarmStub, aged, give_asleep, give_rows, give_stored_rows, use_swarm
from tests.python.cplugs.huddle.test_task_manager_routes import app, client  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_tags import store_of

URL = f"{BASE}/lists/12/lead"
MAIN, AGENT, OTHER = "ses_main", "ses_agent", "ses_other"


@pytest.fixture
def world(app, monkeypatch):
    monkeypatch.setattr(service, "project_names", lambda ctx: {"12": "Carnivore", "13": "Plain"})
    give_asleep(monkeypatch, [{"session_uuid": "u-sleepy", "project_id": 12, "name": "Sleepy"}])
    give_rows(app, [aged(AGENT, 12, 1), aged(MAIN, 12, 9), aged(OTHER, 12, 5), aged("ses_x", 13, 3), aged("ses_y", 13, 2)])
    return use_swarm(monkeypatch, SwarmStub(project_agents={"12": AGENT}))


@pytest.fixture
def ctx(app, world):
    context = runtime.host_for(app).context("huddle", background=True)
    roles_port.register(context)
    yield context
    roles_port.unregister()


def seat(app, list_key: str = "12") -> lead.Seat:
    return RoleStore(store_of(app)).seat(list_key)


def leads(client) -> dict:
    return client.get(f"{BASE}/roles").json()["leads"]


def test_the_default_set_lead_still_repoints_the_agent_and_the_seat_follows(client, world):
    answer = client.put(URL, json={"session": OTHER})
    assert answer.status_code == 200 and world.promoted == [(OTHER, "12")]
    assert (answer.json()["seat"]["session"], answer.json()["seat"]["by"], answer.json()["agent"]) == (OTHER, lead.BY_AGENT, True)
    assert client.put(URL, json={"session": None}).status_code == 400


def test_seat_only_pins_the_seat_and_leaves_the_agent_alone(client, world):
    answer = client.put(URL, json={"session": MAIN, "seat_only": True})
    assert answer.status_code == 200 and world.promoted == [] and world.project_agents == {"12": AGENT}
    assert (answer.json()["seat"]["session"], answer.json()["seat"]["by"]) == (MAIN, lead.BY_PINNED)
    assert leads(client)["12"]["session"] == MAIN and seat(client.app).lead_by == lead.BY_PINNED


def test_a_plain_owner_seat_is_still_overridden_by_the_agent(client, world):
    RoleStore(store_of(client.app)).set_lead("12", MAIN, lead.BY_OWNER)
    assert leads(client)["12"]["session"] == AGENT and seat(client.app).lead_by == lead.BY_AGENT


def test_seat_only_takes_an_asleep_session_and_refuses_one_from_elsewhere_or_with_agent(client, world):
    assert client.put(URL, json={"session": "u-sleepy", "seat_only": True}).json()["seat"]["session"] == "u-sleepy"
    assert client.put(URL, json={"session": "ses_x", "seat_only": True}).status_code == 400
    both = client.put(URL, json={"session": MAIN, "seat_only": True, "agent": True})
    assert both.status_code == 400 and world.promoted == [] and seat(client.app).lead_key == "u-sleepy"


def test_seat_only_null_releases_the_pin_back_to_the_agent(client, world):
    client.put(URL, json={"session": MAIN, "seat_only": True})
    answer = client.put(URL, json={"session": None, "seat_only": True})
    assert answer.status_code == 200 and (seat(client.app).lead_key, seat(client.app).lead_by) == (AGENT, lead.BY_AGENT)


def test_the_default_set_lead_on_a_pinned_project_moves_the_seat_with_the_agent(client, world):
    client.put(URL, json={"session": MAIN, "seat_only": True})
    client.put(URL, json={"session": OTHER})
    assert world.project_agents["12"] == OTHER and (seat(client.app).lead_key, seat(client.app).lead_by) == (OTHER, lead.BY_AGENT)


def test_the_listing_marks_the_pinned_session_as_lead_not_the_agent(app, client, ctx):
    client.put(URL, json={"session": MAIN, "seat_only": True})
    rows = [aged(AGENT, 12, 1), aged(MAIN, 12, 9)]
    flags = asyncio.run(roles_port.register(ctx).read(None, rows))
    assert (flags[MAIN]["lead"], flags[AGENT]["lead"]) == (True, False)
    assert seat(app).lead_key == MAIN


def test_a_pinned_seat_stands_while_its_row_stands_and_follows_the_agent_once_gone(app, client, ctx, monkeypatch):
    client.put(URL, json={"session": MAIN, "seat_only": True})
    give_rows(app, [aged(AGENT, 12, 1), aged(OTHER, 12, 5)])
    give_stored_rows(monkeypatch, {MAIN: StoredRow(12, False)})
    assert asyncio.run(gone.check(ctx)) == [] and (seat(app).lead_key, seat(app).lead_by) == (MAIN, lead.BY_PINNED)
    give_stored_rows(monkeypatch, {MAIN: StoredRow(12, True)})
    assert asyncio.run(gone.check(ctx)) == []
    assert (seat(app).lead_key, seat(app).lead_by) == (AGENT, lead.BY_AGENT)


def test_the_retrofit_reports_a_pinned_seat_instead_of_promoting_it(client, world):
    client.put(f"{BASE}/lists/13/lead", json={"session": "ses_x"})
    before = {r["project"]: r for r in client.get(f"{BASE}/leads/retrofit").json()["plan"]}["Plain"]
    assert (before["action"], before["session"]) == (retrofit.PROMOTE, "ses_x")
    client.put(f"{BASE}/lists/13/lead", json={"session": "ses_x", "seat_only": True})
    client.put(URL, json={"session": MAIN, "seat_only": True})
    plan = {r["project"]: r for r in client.get(f"{BASE}/leads/retrofit").json()["plan"]}
    assert (plan["Plain"]["action"], plan["Plain"]["session"]) == (retrofit.PINNED_SEAT, "ses_x")
    assert (plan["Carnivore"]["action"], plan["Carnivore"]["session"]) == (retrofit.PINNED_SEAT, MAIN)
    run = client.post(f"{BASE}/leads/retrofit", json={"dry_run": False}).json()
    assert run["promoted"] == 0 and world.promoted == [] and seat(client.app, "13").lead_by == lead.BY_PINNED


def test_the_two_step_puts_the_agent_on_a_fresh_session_and_pins_the_seat_to_the_old_body(client, world):
    world.project_agents["12"] = MAIN
    assert leads(client)["12"]["session"] == MAIN and seat(client.app).lead_by == lead.BY_AGENT
    assert client.put(URL, json={"session": AGENT}).status_code == 200
    assert world.project_agents["12"] == AGENT and seat(client.app).lead_key == AGENT
    assert client.put(URL, json={"session": MAIN, "seat_only": True}).status_code == 200
    assert leads(client)["12"]["session"] == MAIN and world.project_agents["12"] == AGENT and world.promoted == [(AGENT, "12")]


def test_the_tool_takes_seat_only_and_its_description_fits_the_cap(app, world):
    context = runtime.host_for(app).context("huddle", background=True)
    args, sentence = asyncio.run(mcp_lead._lead_prepare(context, None, {"list": "12", "session": MAIN, "seat_only": True}))
    assert args["seat_only"] is True and "leaving the Swarm agent alone" in sentence
    with pytest.raises(ToolError, match="cannot be combined"):
        asyncio.run(mcp_lead._lead_prepare(context, None, {"list": "12", "session": MAIN, "seat_only": True, "agent": True}))
    assert all(len(spec.description) <= 400 for spec in mcp_lead.TOOLS.values())
