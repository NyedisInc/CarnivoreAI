
from __future__ import annotations

import asyncio

# ruff: noqa: F811
from src.core.swarm.cards import ops, port as card_port
from tests.python.swarm.cards.test_card_board_actions import client, make, on_board
from tests.python.swarm.cards.test_card_enforcement import call, refused, sql_rows, world  # noqa: F401


def card(cid: int) -> dict:
    return asyncio.run(card_port.get().card(cid))


def test_the_project_agent_queues_its_top_todo_card_and_deals_it(world):
    w = world
    top, lower = make(w, "top work"), make(w, "lower work")
    out = call(w, "boss", "swarm_card_queue", card_id=top)["card"]
    assert out["column"] == "in_progress" and out["queued"] and out["holder"] is None
    dealt = call(w, "boss", "swarm_card_deal", card_id=top, agent_id=w.agents["kid"]["id"])["card"]
    assert dealt["holder"]["agent_id"] == w.agents["kid"]["id"]
    assert card(lower)["column"] == "todo"
    detail = sql_rows(w, "SELECT detail FROM work_card_events WHERE item_id = ? AND kind = 'moved' AND to_col = 'in_progress'", top)[0][0]
    assert "queued by agent" in detail and "top todo card" in detail


def test_queuing_a_lower_card_needs_a_reason_and_the_reason_is_kept(world):
    w = world
    top, lower = make(w, "top work"), make(w, "lower work")
    assert "not_top" in refused(w, "boss", "swarm_card_queue", card_id=lower)
    assert card(lower)["column"] == "todo"
    call(w, "boss", "swarm_card_queue", card_id=lower, reason="the login fix blocks the release")
    detail = sql_rows(w, "SELECT detail FROM work_card_events WHERE item_id = ? AND kind = 'moved' AND to_col = 'in_progress'", lower)[0][0]
    assert f"ahead of #{top}" in detail and "the login fix blocks the release" in detail
    assert card(top)["column"] == "todo"


def test_other_ranks_and_other_projects_are_refused(world):
    w = world
    cid = make(w, "work")
    for slug in ("fixer", "builder", "kid"):
        assert "not_allowed" in refused(w, slug, "swarm_card_queue", card_id=cid)
    other = asyncio.run(ops.create(w.state, None, {"title": "elsewhere", "summary": "s", "list_key": "17"}, by="owner"))["id"]
    assert "not_allowed" in refused(w, "boss", "swarm_card_queue", card_id=other, reason="mine now")
    assert "not_allowed" in refused(w, "fixer", "swarm_card_create", title="t", summary="s", project_id=16, queued=True)
    made = call(w, "boss", "swarm_card_create", title="start now", summary="s", project_id=16, queued=True)["card"]
    assert made["column"] == "in_progress" and made["queued"]
    assert client(w).post(f"/api/v1/swarm/cards/{cid}/queue", json={}).json()["queued"]


def test_an_owner_todo_card_is_never_stranded_and_an_agents_untouched_one_is(world):
    w = world
    mine = asyncio.run(ops.create(w.state, None, {"title": "owner backlog", "summary": "s", "project_id": 16}, by="owner"))["id"]
    agents = make(w, "agent work")
    seen = make(w, "agent work the owner moved")
    asyncio.run(ops.move(w.state, seen, {"before_id": None}, by="owner"))
    board = on_board()
    assert board[agents]["stranded"] and not board[mine]["stranded"] and not board[seen]["stranded"]
    assert board[mine]["column"] == "todo" and not board[mine]["queued"]
    call(w, "boss", "swarm_card_queue", card_id=agents, reason="stranded work card")
    assert not card(agents)["stranded"] and card(mine)["column"] == "todo"
