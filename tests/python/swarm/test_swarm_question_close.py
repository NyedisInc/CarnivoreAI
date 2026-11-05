
from __future__ import annotations

import pytest

from src.core.swarm import facade, question_close, routing
from src.core.swarm.cards import port as card_port
from tests.python.swarm.test_swarm_question_cards import VIEW, Cards, env, run  # noqa: F401

ASK = {"question": "Should the NAS move onto its own network segment before setup?",
       "summary": "Should the family NAS get its own network segment before setup starts?"}
NUMBERED = ("Before setup I need these:\n1. the admin user name\n2. the shared folder names\n\n"
            "- **A. Install DSM.** This erases the drives.\n- **B. Move the NAS.** I recommend yes.")


@pytest.fixture()
def world(env, monkeypatch):
    closed, told = [], []

    async def close_card(item_id, state):
        closed.append((item_id, state))

    async def tell(app_state, agent_id, text, **kw):
        told.append((agent_id, text))
        return False

    env.port.close_card = close_card
    monkeypatch.setattr(routing, "tell", tell)
    card_port.register(Cards("Family NAS build"))
    env.closed, env.told = closed, told
    return env


def state(env, qid):
    row = env.conn.execute("SELECT state, answered_by FROM swarm_questions WHERE id = ?", (qid,)).fetchone()
    return row["state"], row["answered_by"]


def test_a_numbered_list_in_a_plain_question_is_refused_with_the_batch_shape(world):
    assert question_close.list_items(NUMBERED) == 4
    with pytest.raises(routing.QuestionRefused) as refused:
        run(routing.ask(VIEW, None, {**ASK, "question": NUMBERED}))
    assert "4 numbered or lettered items" in str(refused.value) and "`questions`" in str(refused.value)
    assert world.conn.execute("SELECT COUNT(*) FROM swarm_questions").fetchone()[0] == 0
    assert question_close.list_refusal("Pick one: 1. is fine, or option b) works.") is None


def test_the_asker_withdraws_its_open_question_and_its_card_closes(world):
    qid = run(routing.ask(VIEW, None, ASK))["question_id"]
    assert state(world, qid)[0] == "open" and world.port.cards[-1].ref == f"question:{qid}"
    assert run(question_close.withdraw(VIEW, None, {"question_id": qid})) == {"question_id": qid, "closed": True}
    assert state(world, qid) == ("closed", question_close.WITHDRAWN_BY)
    assert world.closed == [(len(world.port.cards), "closed")]
    with pytest.raises(routing.QuestionRefused):
        run(question_close.withdraw(VIEW, None, {"question_id": qid}))


def test_another_agent_cannot_withdraw_a_question_it_did_not_ask(world, monkeypatch):
    qid = run(routing.ask(VIEW, None, ASK))["question_id"]

    async def lead(view, caller):
        return world.lead

    monkeypatch.setattr(routing, "caller_agent", lead)
    with pytest.raises(routing.QuestionRefused, match="not one of your open questions"):
        run(question_close.withdraw(VIEW, None, {"question_id": qid}))
    assert state(world, qid)[0] == "open" and world.closed == []


def test_ask_with_replaces_closes_the_old_question_in_the_same_write(world):
    old = run(routing.ask(VIEW, None, ASK))["question_id"]
    made = run(routing.ask(VIEW, None, {**ASK, "replaces": old}))
    assert made["replaced"] == old and made["question_id"] != old and not made["joined"]
    assert state(world, old) == ("closed", question_close.WITHDRAWN_BY) and state(world, made["question_id"])[0] == "open"
    assert (1, "closed") in world.closed
    with pytest.raises(routing.QuestionRefused):
        run(routing.ask(VIEW, None, {**ASK, "summary": "Another one?", "replaces": old}))
    assert world.conn.execute("SELECT COUNT(*) FROM swarm_questions").fetchone()[0] == 2


def test_the_owner_skips_a_question_card_every_asker_is_told_and_the_card_closes(world, monkeypatch):
    qid = run(routing.ask(VIEW, None, ASK))["question_id"]
    world.told.clear()
    swarm = facade.SwarmFacade.__new__(facade.SwarmFacade)
    swarm._app_state = object()
    monkeypatch.setattr(facade.switch, "is_on", lambda: True)
    assert run(swarm._apply_decision(f"question:{qid}", question_close.SKIP_DECISION, "", "")) is True
    assert state(world, qid) == ("closed", question_close.SKIPPED_BY)
    assert world.told == [(world.research["id"], question_close.skip_text(qid))]
    assert world.closed == [(len(world.port.cards), "closed")]
    with pytest.raises(facade.SwarmError):
        run(swarm._apply_decision(f"question:{qid}", question_close.SKIP_DECISION, "", ""))
