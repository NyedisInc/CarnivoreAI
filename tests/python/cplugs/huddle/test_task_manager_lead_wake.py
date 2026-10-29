
from __future__ import annotations

import pytest

from src.cplugs.huddle.roles import lead
from src.cplugs.huddle.roles.store import RoleStore
from tests.python.cplugs.huddle.roles_rig import BASE, SwarmStub, aged, use_swarm
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, pasted  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_tags import SLEEPER, SEND, World, add, store_of, world  # noqa: F401


def seat(world, key: str) -> None:
    RoleStore(store_of(world.app)).set_lead("12", key, lead.BY_OWNER)


def told(client) -> dict:
    return client.post(SEND, json={"lists": ["12"]}).json()["results"][0]


def test_the_plain_tell_wakes_an_asleep_lead_and_the_task_goes_to_it(client, world, pasted):
    world.sleeper()
    seat(world, SLEEPER)
    add(client)
    result = told(client)
    assert world.woken == [SLEEPER] and result["status"] == "sent" and pasted[-1][0] == SLEEPER


def test_a_live_lead_is_not_woken_again(client, world, pasted):
    seat(world, "ses_new")
    add(client)
    assert told(client)["status"] == "sent" and world.woken == [] and pasted[-1][0] == "ses_new"


def test_a_lead_that_will_not_wake_leaves_the_default_serving(client, world, pasted):
    world.sleeper()
    world.refuse_wake = True
    seat(world, SLEEPER)
    add(client)
    result = told(client)
    assert world.woken == [SLEEPER] and result["status"] == "sent" and pasted[-1][0] == "ses_old"


def test_the_owners_own_pick_outranks_the_lead_and_wakes_nothing(client, world, pasted):
    world.sleeper()
    seat(world, SLEEPER)
    assert client.put(f"{BASE}/lists/12/send-target", json={"target": "ses_new"}).status_code == 200
    add(client)
    assert told(client)["status"] == "sent" and world.woken == [] and pasted[-1][0] == "ses_new"


def test_an_asleep_project_agent_is_woken_through_the_swarm_and_never_behind_its_back(client, world, pasted, monkeypatch):
    stub = use_swarm(monkeypatch, SwarmStub(project_agents={"12": "ses_agent"}))
    stub.on_wake = lambda agent_id, body: world.live.append(aged(body, 12, 0))
    world.sleeper()
    world.asleep[:] = [{"session_uuid": "ses_agent", "project_id": 12, "name": "agent"}]
    assert client.get(f"{BASE}/roles").json()["leads"]["12"]["session"] == "ses_agent"
    add(client)
    result = told(client)
    assert stub.woken == [(10, "manual")] and world.woken == [] and result["status"] == "sent" and pasted[-1][0] == "ses_agent"


def test_a_seat_that_moved_up_to_an_agent_with_no_body_yet_starts_it_and_tells_it(client, world, pasted, monkeypatch):
    from src.cplugs.sdk.swarm import SeatRef

    stub = use_swarm(monkeypatch, SwarmStub(fallbacks={"12": SeatRef(7, "alpha", None, None, False, "SysOp")}))
    stub.on_wake = lambda agent_id, body: world.live.append(aged(body, 1, 0))
    seat(world, "swarm:7")
    add(client)
    result = told(client)
    assert stub.woken == [(7, "manual")] and result["status"] == "sent" and pasted[-1][0] == "ses_swarm_7"
