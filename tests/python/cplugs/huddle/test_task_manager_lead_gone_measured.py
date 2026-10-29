
from __future__ import annotations

import asyncio
import threading

import pytest

from src.cplugs.host import runtime
from src.cplugs.huddle import rules
from src.cplugs.huddle.roles import ask, gone, lead, port as roles_port
from src.cplugs.huddle.roles.store import RoleStore
from src.cplugs.sdk.session_rows import SessionRowsUnreadable, StoredRow
from src.cplugs.sdk.swarm import SeatRef
from tests.python.cplugs.huddle.roles_rig import BASE, SwarmStub, aged, give_asleep, give_rows, give_stored_rows, use_swarm
from tests.python.cplugs.huddle.test_task_manager_routes import app, client  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_tags import store_of

SYSOP = SeatRef(1, "alpha", None, None, False, "SysOp")
LEAD = "ses_omega"


@pytest.fixture
def ctx(app, monkeypatch):
    give_asleep(monkeypatch, [])
    give_rows(app, [aged("ses_b", 12, 1)])
    use_swarm(monkeypatch, SwarmStub(fallbacks={"12": SYSOP}))
    context = runtime.host_for(app).context("huddle", background=True)
    roles_port.register(context)
    yield context
    roles_port.unregister()


def seat_of(app):
    return RoleStore(store_of(app)).seat("12")


def open_questions(app) -> list:
    return [m for item in store_of(app).list_items("12")["items"] for m in item["thread"]
            if m["kind"] == "question" and not m["answered"] and m["category"] == ask.LEAD_GONE]


def options_of(client, question) -> dict:
    form = client.get(f"{BASE}/questions/{question['id']}").json()
    return {o["id"]: o["label"] for o in form["ask"]["questions"][0]["options"]}


def test_a_lead_missing_from_one_listing_pass_whose_row_stands_is_not_gone(app, ctx, monkeypatch):
    give_stored_rows(monkeypatch, {LEAD: StoredRow(12, False)})
    RoleStore(store_of(app)).set_lead("12", LEAD, lead.BY_AUTO)
    assert asyncio.run(gone.check(ctx)) == []
    assert (seat_of(app).lead_key, open_questions(app)) == (LEAD, [])


def test_the_listing_pass_itself_leaves_a_re_adopting_lead_seated(app, ctx, monkeypatch):
    give_stored_rows(monkeypatch, {LEAD: StoredRow(12, False)})
    RoleStore(store_of(app)).set_lead("12", LEAD, lead.BY_AUTO)
    port = roles_port.register(ctx)
    asyncio.run(port.read(None, [aged("ses_b", 12, 1)]))
    assert (seat_of(app).lead_key, open_questions(app)) == (LEAD, [])


@pytest.mark.parametrize("stored", [{LEAD: StoredRow(12, True)}, {}, {LEAD: StoredRow(99, False)}], ids=["archived", "deleted", "moved"])
def test_an_archived_deleted_or_moved_lead_is_gone(app, ctx, monkeypatch, stored):
    give_stored_rows(monkeypatch, stored)
    RoleStore(store_of(app)).set_lead("12", LEAD, lead.BY_AUTO)
    asyncio.run(gone.check(ctx))
    assert seat_of(app).lead_key == "swarm:1" and len(open_questions(app)) == 1


def test_an_unreadable_row_decides_nothing(app, ctx, monkeypatch):
    give_stored_rows(monkeypatch, SessionRowsUnreadable("OperationalError"))
    RoleStore(store_of(app)).set_lead("12", LEAD, lead.BY_AUTO)
    assert asyncio.run(roles_port.register(ctx).check_gone()) is False
    assert (seat_of(app).lead_key, open_questions(app)) == (LEAD, [])


class RacingSwarm(SwarmStub):

    def __init__(self) -> None:
        super().__init__(fallbacks={"12": SYSOP})
        self.barrier = threading.Barrier(2)

    def fallback_agent(self, project_key: str):
        try:
            self.barrier.wait(timeout=1.0)
        except threading.BrokenBarrierError:
            pass
        return super().fallback_agent(project_key)


def test_two_checks_at_once_ask_one_question(app, ctx, monkeypatch):
    use_swarm(monkeypatch, RacingSwarm())
    RoleStore(store_of(app)).set_lead("12", LEAD, lead.BY_AUTO)

    async def both():
        return await asyncio.gather(gone.check(ctx), gone.check(ctx))

    first, second = asyncio.run(both())
    assert len(first) + len(second) == 1 and len(open_questions(app)) == 1


def carriers(app) -> list:
    return [i["id"] for i in store_of(app).list_items("12")["items"] if i["title"] == gone.CARRIER_TITLE]


def test_a_second_open_question_on_the_list_is_withdrawn_and_the_answer_clears_both_carriers(app, ctx, client):
    RoleStore(store_of(app)).set_lead("12", LEAD, lead.BY_AUTO)
    asyncio.run(gone.check(ctx))
    extra = store_of(app).add("12", "the lead of this project is gone", actor="claude", created_key=rules.CARNIVORE_KEY,
                              title=gone.CARRIER_TITLE)
    ask.carnivore_ask(store_of(app), extra["id"], category=ask.LEAD_GONE, context="x", options=[gone.KEEP, "later"])
    assert len(open_questions(app)) == 2
    asyncio.run(gone.check(ctx))
    [question] = open_questions(app)
    assert len(carriers(app)) == 2
    client.post(f"{BASE}/questions/{question['id']}/answer", json={"answers": {"q1": {"choice": gone.option_id("ses_b")}}})
    assert seat_of(app).lead_key == "ses_b" and carriers(app) == []


def test_an_open_question_offers_the_projects_sessions_by_title_and_the_pick_is_carried_out(app, ctx, client, monkeypatch):
    give_rows(app, [])
    RoleStore(store_of(app)).set_lead("12", LEAD, lead.BY_AUTO)
    asyncio.run(gone.check(ctx))
    assert set(options_of(client, open_questions(app)[0])) == {gone.KEEP, "later"}
    give_rows(app, [aged("ses_b", 12, 1)])
    give_asleep(monkeypatch, [{"session_uuid": "u-sleepy", "project_id": 12, "name": "Agent - Sleepy"}])
    asyncio.run(gone.check(ctx))
    [question] = open_questions(app)
    assert options_of(client, question) == {gone.option_id("u-sleepy"): "Agent - Sleepy", gone.option_id("ses_b"): "ses_b", gone.KEEP: "keep SysOp"}
    answer = client.post(f"{BASE}/questions/{question['id']}/answer", json={"answers": {"q1": {"choice": gone.option_id("u-sleepy")}}})
    assert answer.status_code == 200
    seat = seat_of(app)
    assert (seat.lead_key, seat.lead_by) == ("u-sleepy", lead.BY_OWNER) and open_questions(app) == []


def test_a_pick_that_is_no_longer_a_session_of_the_project_asks_again(app, ctx, client):
    RoleStore(store_of(app)).set_lead("12", LEAD, lead.BY_AUTO)
    asyncio.run(gone.check(ctx))
    [question] = open_questions(app)
    give_rows(app, [aged("ses_c", 12, 1)])
    client.post(f"{BASE}/questions/{question['id']}/answer", json={"answers": {"q1": {"choice": gone.option_id("ses_b")}}})
    [again] = open_questions(app)
    assert seat_of(app).lead_key == "swarm:1" and gone.option_id("ses_c") in options_of(client, again)
