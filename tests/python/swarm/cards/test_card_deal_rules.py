
from __future__ import annotations

import asyncio

# ruff: noqa: F811
from src.core.swarm import body
from src.core.swarm.cards import ops, port as card_port
from tests.python.swarm.cards.test_card_board_actions import make
from tests.python.swarm.cards.test_card_enforcement import call, refused, sql_rows, world  # noqa: F401


def queued(w, title: str) -> int:
    cid = make(w, title)
    asyncio.run(ops.set_column(w.state, cid, {"column": "in_progress"}, by="owner"))
    return cid


def holder(cid: int):
    return (asyncio.run(card_port.get().card(cid)).get("holder") or {}).get("agent_id")


def test_no_card_id_deals_the_top_queued_card_and_a_lower_one_needs_a_reason(world):
    w = world
    top, lower = queued(w, "top work"), queued(w, "lower work")
    fixer = w.agents["fixer"]["id"]
    assert "not_top" in refused(w, "boss", "swarm_card_deal", card_id=lower, agent_id=fixer)
    assert holder(lower) is None
    assert call(w, "boss", "swarm_card_deal", agent_id=fixer)["card"]["id"] == top
    other = queued(w, "next work")
    call(w, "boss", "swarm_card_deal", card_id=other, agent_id=w.agents["kid"]["id"], reason="the kid already knows this code")
    detail = sql_rows(w, "SELECT detail FROM work_card_events WHERE item_id = ? AND kind = 'noted'", other)[0][0]
    assert f"ahead of #{lower}" in detail and "already knows this code" in detail


def test_a_card_in_a_specialists_domain_goes_to_that_specialist_unless_a_reason_is_given(world):
    w = world
    builder, fixer = w.agents["builder"]["id"], w.agents["fixer"]["id"]
    asyncio.run(body.run_db(lambda c: c.execute("UPDATE swarm_agents SET specialty = 'Icon Design', project_id = 16 WHERE id = ?", (builder,))))
    cid = queued(w, "icon design for the board header")
    assert "not_fit" in refused(w, "boss", "swarm_card_deal", card_id=cid, agent_id=fixer)
    call(w, "boss", "swarm_card_deal", card_id=cid, agent_id=fixer, reason="the specialist is busy on the release")
    assert holder(cid) == fixer
    detail = sql_rows(w, "SELECT detail FROM work_card_events WHERE item_id = ? AND kind = 'noted'", cid)[0][0]
    assert f"dealt to agent {fixer}" in detail and "busy on the release" in detail
    plain = queued(w, "fix the login page")
    assert call(w, "boss", "swarm_card_deal", card_id=plain, agent_id=fixer)["card"]["holder"]["agent_id"] == fixer
