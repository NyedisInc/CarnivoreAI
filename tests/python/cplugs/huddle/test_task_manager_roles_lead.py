
from __future__ import annotations

import asyncio

import pytest

from src.cplugs.huddle import service
from src.cplugs.huddle.nudge_store import NudgeStore
from src.cplugs.huddle.roles import lead, route, service as roles_service
from src.cplugs.huddle.roles.store import RoleStore, SeatTaken
from tests.python.cplugs.huddle.roles_rig import BASE, SwarmStub, aged, give_asleep, give_rows, use_swarm
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_schedule import env  # noqa: F401

SEAT = lead.Seat("12", lead_key="a", lead_by=lead.BY_OWNER, lead_at=1.0, ever_led=True)


def test_standing_keeps_an_asleep_lead_and_calls_only_a_missing_one_gone():
    assert lead.standing(SEAT, {"a"}, set()) == ("a", None)
    assert lead.standing(SEAT, set(), {"a"}) == ("a", None)
    assert lead.standing(SEAT, {"b"}, {"c"}) == (None, lead.VACANT_GONE)
    assert lead.standing(lead.Seat("12"), {"a"}, set()) == (None, lead.VACANT_EMPTY)


def test_the_first_ever_pick_is_the_earliest_non_dnd_session_and_only_while_never_led():
    never = lead.Seat("12")
    pool = [lead.Candidate("late", 9.0), lead.Candidate("early", 1.0, dnd=True), lead.Candidate("mid", 5.0)]
    assert lead.auto_pick(never, pool) == "mid"
    assert lead.auto_pick(never, [lead.Candidate("x", 1.0, dnd=True)]) is None and lead.auto_pick(never, []) is None
    assert lead.auto_pick(lead.Seat("12", ever_led=True), pool) is None


def test_a_session_may_take_the_seat_only_while_it_is_vacant_or_already_its_own():
    assert lead.may_take(lead.Seat("12"), {"a"}, set(), "b") and lead.may_take(SEAT, {"a"}, set(), "a")
    assert not lead.may_take(SEAT, {"a"}, set(), "b") and not lead.may_take(SEAT, set(), {"a"}, "b")
    assert lead.may_take(SEAT, set(), set(), "b")


def test_a_seat_keyed_on_a_swarm_agent_round_trips_and_the_old_swarm_deferral_is_gone():
    assert lead.fallback_key(3) == "swarm:3" and lead.fallback_agent_id("swarm:3") == 3
    assert lead.fallback_agent_id("7f3e-a") is None and lead.fallback_agent_id("swarm:x") is None
    for retired in ("duty_active", "dealer_active", "defers_to_swarm", "DEFERS_SETTING"):
        assert not hasattr(lead, retired), retired


@pytest.mark.parametrize("fields,offered", [
    ({}, True),
    ({"lane": "swarm"}, False),
    ({"card_holder": "x"}, False),
    ({"card_dealt_to": "x"}, False),
])
def test_may_offer(fields, offered):
    task = {"lane": "task_manager", "card_holder": None, "card_dealt_to": None, **fields}
    assert lead.may_offer(task) is offered


def test_the_seat_store_keeps_ever_led_after_a_release_and_refuses_a_second_taker(env):
    roles = RoleStore(env.store)
    assert roles.seat("12") == lead.Seat("12")
    roles.set_lead("12", "a", lead.BY_OWNER)
    released = roles.set_lead("12", "", lead.BY_OWNER)
    assert released.lead_key == "" and released.ever_led is True
    with pytest.raises(SeatTaken):
        roles.take_if_vacant("12", "b", {"b"}, set(), lead.BY_AUTO)
    assert roles.take_if_vacant("12", "b", {"b"}, set(), lead.BY_SESSION).lead_key == "b"
    with pytest.raises(SeatTaken) as held:
        roles.take_if_vacant("12", "c", {"b", "c"}, set(), lead.BY_SESSION)
    assert held.value.holder == "b"
    assert roles.take_if_vacant("12", "c", {"c"}, set(), lead.BY_SESSION).lead_key == "c"


def test_dnd_and_the_nudge_switch_share_a_row_without_touching_each_other(env):
    roles, nudge = RoleStore(env.store), NudgeStore(env.store)
    roles.set_dnd("s1", True)
    assert nudge.session_prefs() == {}
    nudge.set_session_pref("s1", True)
    assert roles.dnd_keys() == {"s1"} and nudge.session_prefs() == {"s1": True}
    roles.set_dnd("s1", False)
    assert roles.dnd_keys() == frozenset() and nudge.session_prefs() == {"s1": True}


def measure(env):
    return asyncio.run(roles_service.measure(env.ctx))


def test_the_first_session_in_a_project_is_seated_once_and_nothing_succeeds_it(env, monkeypatch):
    give_asleep(monkeypatch, [])
    env.set_rows([aged("ses_new", 12, 1), aged("ses_old", 12, 5), aged("ses_other", 99, 9)])
    roles = RoleStore(env.store)
    seats = roles_service.evaluate(roles, measure(env))
    assert (seats["12"].lead_key, seats["12"].lead_by) == ("ses_old", lead.BY_AUTO) and "99" in seats
    roles.set_lead("12", "", lead.BY_OWNER)
    assert roles_service.evaluate(roles, measure(env))["12"].lead_key == ""


def test_do_not_disturb_and_swarm_bodies_are_not_picked(env, monkeypatch):
    give_asleep(monkeypatch, [])
    use_swarm(monkeypatch, SwarmStub(bodies={"ses_body"}))
    env.set_rows([aged("ses_body", 12, 9), aged("ses_dnd", 12, 8), aged("ses_ok", 12, 1)])
    roles = RoleStore(env.store)
    roles.set_dnd("ses_dnd", True)
    assert roles_service.evaluate(roles, measure(env))["12"].lead_key == "ses_ok"


def test_an_asleep_lead_stays_lead_and_an_archived_one_reads_vacant_with_its_key_kept(env, monkeypatch):
    env.set_rows([aged("ses_new", 12, 1)])
    roles = RoleStore(env.store)
    roles.set_lead("12", "ses_sleepy", lead.BY_OWNER)
    give_asleep(monkeypatch, [{"session_uuid": "ses_sleepy", "project_id": 12, "name": "sleepy"}])
    roster = measure(env)
    assert roles_service.holder_of(roles.seat("12"), roster) == ("ses_sleepy", None)
    give_asleep(monkeypatch, [{"session_uuid": "ses_sleepy", "project_id": 99, "name": "moved"}])
    holder, reason = roles_service.holder_of(roles.seat("12"), measure(env))
    assert (holder, reason) == (None, lead.VACANT_GONE) and roles.seat("12").lead_key == "ses_sleepy"


def default_of(client, key: str = "12") -> tuple:
    body = client.get(f"{BASE}/lists/{key}/sessions").json()
    return body["default"], body["reason"]


def test_the_tell_goes_to_the_lead_ahead_of_the_default_and_the_owners_pick_beats_the_lead(client, app, monkeypatch):
    give_asleep(monkeypatch, [])
    give_rows(app, [aged("ses_old", 12, 5), aged("ses_new", 12, 1)])
    note(app, "ses_old", "12", 100.0)
    assert default_of(client) == ("ses_old", "last_task_manager_caller")
    assert client.put(f"{BASE}/lists/12/lead", json={"session": "ses_new"}).status_code == 200
    assert default_of(client) == ("ses_new", route.REASON_LEAD)
    assert client.put(f"{BASE}/lists/12/send-target", json={"target": "ses_old"}).status_code == 200
    assert default_of(client) == ("ses_old", "picked")


def test_a_lead_cannot_go_on_dnd_and_taking_the_seat_clears_a_dnd_the_session_had(client, app, monkeypatch):
    give_asleep(monkeypatch, [])
    give_rows(app, [aged("ses_old", 12, 5), aged("ses_new", 12, 1)])
    note(app, "ses_old", "12", 100.0)
    client.put(f"{BASE}/sessions/ses_new/dnd", json={"dnd": True})
    seated = client.put(f"{BASE}/lists/12/lead", json={"session": "ses_new"})
    assert seated.status_code == 200 and seated.json()["dnd_cleared"] is True
    assert client.get(f"{BASE}/roles").json()["dnd"] == []
    refused = client.put(f"{BASE}/sessions/ses_new/dnd", json={"dnd": True})
    assert refused.status_code == 400 and "lead cannot go on do not disturb" in refused.json()["detail"]["detail"]
    assert client.put(f"{BASE}/sessions/ses_old/dnd", json={"dnd": True}).status_code == 200
    assert default_of(client) == ("ses_new", route.REASON_LEAD)


def test_the_project_agent_is_the_lead_and_the_old_step_aside_is_gone(client, app, monkeypatch):
    give_asleep(monkeypatch, [])
    give_rows(app, [aged("ses_old", 12, 5), aged("ses_agent", 12, 1)])
    note(app, "ses_old", "12", 100.0)
    use_swarm(monkeypatch, SwarmStub(project_agents={"12": "ses_agent"}))
    roles = client.get(f"{BASE}/roles").json()["leads"]["12"]
    assert (roles["session"], roles["by"]) == ("ses_agent", lead.BY_AGENT)
    assert default_of(client) == ("ses_agent", route.REASON_LEAD)


def test_the_owner_clearing_a_project_with_an_agent_is_refused_and_a_plain_project_clears(client, app, monkeypatch):
    give_asleep(monkeypatch, [])
    give_rows(app, [aged("ses_old", 12, 5), aged("ses_agent", 12, 1)])
    stub = use_swarm(monkeypatch, SwarmStub(project_agents={"12": "ses_agent"}))
    refused = client.put(f"{BASE}/lists/12/lead", json={"session": None})
    assert refused.status_code == 400 and "Swarm project agent" in refused.json()["detail"]["detail"]
    stub.project_agents.clear()
    stub.agent_projects.clear()
    assert client.put(f"{BASE}/lists/12/lead", json={"session": None}).status_code == 200


def test_set_lead_on_a_project_with_an_agent_repoints_the_agent_and_the_seat_follows(client, app, monkeypatch):
    give_asleep(monkeypatch, [])
    give_rows(app, [aged("ses_old", 12, 5), aged("ses_agent", 12, 1)])
    stub = use_swarm(monkeypatch, SwarmStub(project_agents={"12": "ses_agent"}))
    answer = client.put(f"{BASE}/lists/12/lead", json={"session": "ses_old"}).json()
    assert stub.promoted == [("ses_old", "12")] and answer["agent"] is True
    assert answer["seat"]["session"] == "ses_old" and client.get(f"{BASE}/roles").json()["leads"]["12"]["by"] == lead.BY_AGENT
    stub.promoted.clear()
    client.put(f"{BASE}/lists/12/lead", json={"session": "ses_old"})
    assert stub.promoted == []


def test_set_lead_on_a_project_without_an_agent_is_the_plain_seat_unless_asked_to_promote(client, app, monkeypatch):
    give_asleep(monkeypatch, [])
    give_rows(app, [aged("ses_old", 12, 5), aged("ses_new", 12, 1)])
    stub = use_swarm(monkeypatch, SwarmStub())
    assert client.put(f"{BASE}/lists/12/lead", json={"session": "ses_new"}).json()["agent"] is False and stub.promoted == []
    answer = client.put(f"{BASE}/lists/12/lead", json={"session": "ses_old", "agent": True}).json()
    assert stub.promoted == [("ses_old", "12")] and answer["agent"] is True


def test_a_refused_promotion_is_a_400_with_the_swarms_sentence_and_changes_no_seat(client, app, monkeypatch):
    from src.cplugs.sdk.swarm import SwarmError

    give_asleep(monkeypatch, [])
    give_rows(app, [aged("ses_old", 12, 5), aged("ses_agent", 12, 1)])
    stub = use_swarm(monkeypatch, SwarmStub(project_agents={"12": "ses_agent"}))

    async def refuse(session_uuid, project_key):
        raise SwarmError("ses_old is working a turn; try again when it is idle")

    stub.promote_session = refuse
    answer = client.put(f"{BASE}/lists/12/lead", json={"session": "ses_old"})
    assert answer.status_code == 400 and "working a turn" in answer.json()["detail"]["detail"]
    assert client.get(f"{BASE}/roles").json()["leads"]["12"]["session"] == "ses_agent"


def test_set_lead_with_agent_on_an_hq_project_promotes_into_the_company_agent_through_the_swarm(client, app, monkeypatch):
    give_asleep(monkeypatch, [])
    give_rows(app, [aged("ses_hq", 12, 3)])
    stub = use_swarm(monkeypatch, SwarmStub(hqs={"12": 5}))
    answer = client.put(f"{BASE}/lists/12/lead", json={"session": "ses_hq", "agent": True}).json()
    assert stub.promoted == [("ses_hq", "12")] and answer["agent"] is True and answer["seat"]["session"] == "ses_hq"
    assert client.get(f"{BASE}/roles").json()["leads"]["12"]["by"] == lead.BY_AGENT
