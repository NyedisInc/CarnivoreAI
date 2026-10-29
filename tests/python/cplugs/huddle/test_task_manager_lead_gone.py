
from __future__ import annotations

import asyncio

import pytest

from src.cplugs.host import runtime
from src.cplugs.huddle.roles import ask, gone, lead, port as roles_port
from src.cplugs.huddle.roles.store import RoleStore
from src.cplugs.sdk.swarm import SeatRef
from tests.python.cplugs.huddle.roles_rig import BASE, SwarmStub, aged, give_asleep, give_rows, use_swarm
from tests.python.cplugs.huddle.test_task_manager_routes import app, client  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_tags import store_of

COMPANY = SeatRef(5, "company", None, "u-company", False, "Acme")
SYSOP = SeatRef(1, "alpha", None, None, False, "SysOp")


@pytest.fixture
def ctx(app, monkeypatch):
    give_asleep(monkeypatch, [])
    give_rows(app, [aged("ses_a", 12, 5), aged("ses_b", 12, 1)])
    context = runtime.host_for(app).context("huddle", background=True)
    roles_port.register(context)
    yield context
    roles_port.unregister()


def seat_of(app, key: str = "12"):
    return RoleStore(store_of(app)).seat(key)


def questions(app) -> list:
    st = store_of(app)
    out = []
    for item in st.list_items("12")["items"]:
        for m in item["thread"]:
            if m["kind"] == "question" and not m["answered"] and m["category"] == ask.LEAD_GONE:
                out.append(m)
    return out


def check(ctx):
    return asyncio.run(gone.check(ctx))


def test_an_archived_lead_moves_the_seat_to_the_company_agent_and_raises_one_question(app, ctx, monkeypatch):
    use_swarm(monkeypatch, SwarmStub(fallbacks={"12": COMPANY}))
    RoleStore(store_of(app)).set_lead("12", "ses_gone", lead.BY_OWNER)
    acted = check(ctx)
    seat = seat_of(app)
    assert (seat.lead_key, seat.lead_by) == ("swarm:5", lead.BY_FALLBACK) and acted[0]["moved_to"] == "Acme"
    assert len(questions(app)) == 1
    assert check(ctx) == [] and len(questions(app)) == 1


def test_without_a_company_the_seat_goes_to_sysop_and_without_either_it_is_emptied(app, ctx, monkeypatch):
    use_swarm(monkeypatch, SwarmStub(fallbacks={"12": SYSOP}))
    RoleStore(store_of(app)).set_lead("12", "ses_gone", lead.BY_OWNER)
    check(ctx)
    assert seat_of(app).lead_key == "swarm:1"
    use_swarm(monkeypatch, SwarmStub())
    RoleStore(store_of(app)).set_lead("12", "ses_gone2", lead.BY_OWNER)
    check(ctx)
    seat = seat_of(app)
    assert seat.lead_key == "" and seat.ever_led


def test_an_asleep_lead_is_never_gone(app, ctx, monkeypatch):
    use_swarm(monkeypatch, SwarmStub(fallbacks={"12": COMPANY}))
    give_asleep(monkeypatch, [{"session_uuid": "ses_sleepy", "project_id": 12, "name": "sleepy"}])
    RoleStore(store_of(app)).set_lead("12", "ses_sleepy", lead.BY_OWNER)
    assert check(ctx) == [] and seat_of(app).lead_key == "ses_sleepy" and questions(app) == []


def test_a_project_agent_whose_body_row_is_gone_is_retired_and_the_seat_moves_up(app, ctx, monkeypatch):
    stub = use_swarm(monkeypatch, SwarmStub(project_agents={"12": "u-dead"}, dead={"12"}, fallbacks={"12": COMPANY}))
    RoleStore(store_of(app)).set_lead("12", "u-dead", lead.BY_AGENT)
    check(ctx)
    assert stub.retired == [10] and seat_of(app).lead_key == "swarm:5" and len(questions(app)) == 1


def test_a_seat_that_moved_up_stands_while_that_agent_lives_and_the_owner_picks_a_new_lead(app, ctx, client, monkeypatch):
    stub = use_swarm(monkeypatch, SwarmStub(fallbacks={"12": COMPANY}))
    RoleStore(store_of(app)).set_lead("12", "ses_gone", lead.BY_OWNER)
    check(ctx)
    question = questions(app)[0]
    form = client.get(f"{BASE}/questions/{question['id']}").json()
    assert {o["id"]: o["label"] for o in form["ask"]["questions"][0]["options"]} == {
        gone.option_id("ses_a"): "ses_a", gone.option_id("ses_b"): "ses_b", gone.KEEP: "keep Acme"}
    answer = client.post(f"{BASE}/questions/{question['id']}/answer", json={"answers": {"q1": {"choice": gone.option_id("ses_b")}}})
    assert answer.status_code == 200
    seat = seat_of(app)
    assert (seat.lead_key, seat.lead_by) == ("ses_b", lead.BY_OWNER) and questions(app) == []
    assert stub.promoted == []


def test_keeping_the_fallback_changes_nothing(app, ctx, client, monkeypatch):
    use_swarm(monkeypatch, SwarmStub(fallbacks={"12": COMPANY}))
    RoleStore(store_of(app)).set_lead("12", "ses_gone", lead.BY_OWNER)
    check(ctx)
    question = questions(app)[0]
    client.post(f"{BASE}/questions/{question['id']}/answer", json={"answers": {"q1": {"choice": gone.KEEP}}})
    assert seat_of(app).lead_key == "swarm:5" and questions(app) == []
