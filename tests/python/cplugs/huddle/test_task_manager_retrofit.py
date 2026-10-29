
from __future__ import annotations

import pytest

from src.cplugs.huddle import service
from src.cplugs.huddle.roles import lead, retrofit
from tests.python.cplugs.huddle.roles_rig import BASE, SwarmStub, aged, give_asleep, give_rows, use_swarm
from tests.python.cplugs.huddle.test_task_manager_routes import app, client  # noqa: F401

URL = f"{BASE}/leads/retrofit"


@pytest.fixture
def world(app, client, monkeypatch):
    monkeypatch.setattr(service, "project_names", lambda ctx: {"12": "carnivore", "13": "Fleet", "14": "Empty", "15": "Agented"})
    give_asleep(monkeypatch, [{"session_uuid": "u-fleet", "project_id": 13, "name": "Fleet"}])
    give_rows(app, [aged("ses_old", 12, 5), aged("ses_new", 12, 1), aged("ses_infra", 13, 4), aged("ses_ag", 15, 1)])
    stub = use_swarm(monkeypatch, SwarmStub(project_agents={"15": "ses_ag"}))
    client.put(f"{BASE}/lists/12/lead", json={"session": "ses_new"})
    client.put(f"{BASE}/lists/13/lead", json={"session": "ses_infra"})
    return stub


def rows_by_project(body: dict) -> dict:
    return {r["project"]: r for r in body["plan"]}


def test_the_dry_run_plan_names_the_sessions_and_changes_nothing(client, world):
    body = client.get(URL).json()
    plan = rows_by_project(body)
    assert body["dry_run"] is True and world.promoted == []
    assert (plan["carnivore"]["action"], plan["carnivore"]["session"], plan["carnivore"]["state"]) == (retrofit.PROMOTE, "ses_new", "live")
    assert plan["Empty"]["action"] == retrofit.NO_LEAD and plan["Agented"]["action"] == retrofit.ALREADY_AGENT
    assert plan["Fleet"]["session_name"] == "ses_infra"


def test_picks_replace_the_current_lead_by_session_name_and_a_bad_pick_is_named(client, world):
    body = client.post(URL, json={"picks": {"Fleet": "Fleet"}}).json()
    fleet = rows_by_project(body)["Fleet"]
    assert (fleet["action"], fleet["session"], fleet["state"], fleet["reason"]) == (retrofit.PROMOTE, "u-fleet", "asleep", "the owner's pick")
    bad = rows_by_project(client.post(URL, json={"picks": {"13": "Nobody"}}).json())["Fleet"]
    assert bad["action"] == retrofit.BAD_PICK and world.promoted == []


def test_the_skip_list_leaves_a_project_alone_by_name_or_id(client, world):
    plan = rows_by_project(client.post(URL, json={"skip": ["Fleet", "12"]}).json())
    assert plan["Fleet"]["action"] == plan["carnivore"]["action"] == retrofit.SKIPPED


def test_a_real_run_promotes_each_planned_session_and_reports_a_refusal_without_stopping(client, world):
    from src.cplugs.sdk.swarm import SwarmError

    real = world.promote_session

    async def promote(session_uuid, project_key):
        if project_key == "13":
            raise SwarmError("Fleet is working a turn; try again when it is idle")
        return await real(session_uuid, project_key)

    world.promote_session = promote
    body = client.post(URL, json={"dry_run": False}).json()
    plan = rows_by_project(body)
    assert (body["promoted"], body["refused"]) == (1, 1) and world.promoted == [("ses_new", "12")]
    assert plan["Fleet"]["outcome"] == retrofit.REFUSED and "working a turn" in plan["Fleet"]["detail"]
    assert client.get(f"{BASE}/roles").json()["leads"]["12"]["by"] == lead.BY_AGENT


def test_a_seat_kept_for_an_archived_project_is_cleared_by_a_real_run_only(client, world, monkeypatch):
    monkeypatch.setattr(service, "project_names", lambda ctx: {"13": "Fleet", "15": "Agented"})
    plan = client.get(URL).json()["plan"]
    stale = next(r for r in plan if r["list"] == "12")
    assert stale["action"] == retrofit.CLEAR_SEAT and stale["session"] == "ses_new"
    assert client.get(f"{BASE}/roles").json()["leads"]["12"]["session"] == "ses_new"
    body = client.post(URL, json={"dry_run": False}).json()
    assert body["cleared"] == 1 and client.get(f"{BASE}/roles").json()["leads"].get("12", {}).get("session") is None



def test_a_project_with_no_seat_and_one_asleep_session_promotes_that_session_and_two_sessions_are_left_to_the_owner(client, world, monkeypatch):
    monkeypatch.setattr(service, "project_names", lambda ctx: {"12": "carnivore", "16": "Lone", "17": "Pair"})
    give_asleep(monkeypatch, [{"session_uuid": "u-lone", "project_id": 16, "name": "Lone Wolf"},
                              {"session_uuid": "u-a", "project_id": 17, "name": "A"}, {"session_uuid": "u-b", "project_id": 17, "name": "B"}])
    plan = rows_by_project(client.get(URL).json())
    assert (plan["Lone"]["action"], plan["Lone"]["session"], plan["Lone"]["state"], plan["Lone"]["reason"]) == (retrofit.PROMOTE, "u-lone", "asleep", "its only session")
    assert plan["Pair"]["action"] == retrofit.NO_LEAD


def test_an_hq_project_plans_promote_company_and_a_real_run_promotes_it_through_the_same_call(client, world):
    world.hqs["13"] = 5
    plan = rows_by_project(client.post(URL, json={"picks": {"Fleet": "Fleet"}}).json())
    assert (plan["Fleet"]["action"], plan["Fleet"]["session"], plan["carnivore"]["action"]) == (retrofit.PROMOTE_COMPANY, "u-fleet", retrofit.PROMOTE)
    assert world.promoted == []
    body = client.post(URL, json={"dry_run": False, "picks": {"Fleet": "Fleet"}}).json()
    assert body["promoted"] == 2 and ("u-fleet", "13") in world.promoted
    assert rows_by_project(body)["Fleet"]["outcome"] == retrofit.DONE


def test_a_company_agent_with_an_hq_project_is_that_projects_lead_agent():
    from src.cplugs.huddle.roles import service as roles_service
    from src.cplugs.sdk.swarm import SeatRef

    roster = roles_service.Roster(agents=(SeatRef(7, "company", "9", "u-amerifund"), SeatRef(8, "company", None, "u-nohq"), SeatRef(9, "alpha", None, "u-alpha")))
    assert roster.project_agents == {"9": "u-amerifund"}


def test_the_approval_sentence_names_each_running_session_that_is_stopped_and_resumed(app, world, monkeypatch):
    import asyncio

    from src.cplugs.host import runtime
    from src.cplugs.huddle.roles import mcp_lead

    context = runtime.host_for(app).context("huddle", background=True)
    _args, sentence = asyncio.run(mcp_lead._retrofit_prepare(context, None, {"picks": {"Fleet": "Fleet"}}))
    assert "STOPPED AND RESUMED (running now): carnivore: ses_new" in sentence
    assert "Fleet: Fleet" in sentence.split("STOPPED AND RESUMED")[0] and "Fleet: Fleet" not in sentence.split("STOPPED AND RESUMED")[1]
