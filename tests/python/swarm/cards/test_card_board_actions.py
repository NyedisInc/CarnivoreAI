
from __future__ import annotations

import asyncio
from typing import Any, Dict, Iterator, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ruff: noqa: E402, F811
from src.api import swarm_card_routes
from src.api.auth import require_auth
from src.core.mcp import card_tools
from src.core.swarm.cards import board, dealer, notices, ops, port as card_port
from tests.python.swarm.cards.test_card_capacity import dealing_step
from tests.python.swarm.cards.test_card_enforcement import call, dealt_to, refused, sql_rows, world  # noqa: F401


@pytest.fixture(autouse=True)
def clean_windows():
    notices.reset()
    yield
    notices.reset()


def make(w, title: str = "work", summary: str = "a plain line") -> int:
    return call(w, "boss", "swarm_card_create", summary=summary, title=title, project_id=16)["card"]["id"]


def walk(node: Any) -> Iterator[Dict[str, Any]]:
    if isinstance(node, dict):
        if "id" in node and "column" in node:
            yield node
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


def on_board(archived: str = "hide") -> Dict[int, Dict[str, Any]]:
    return {c["id"]: c for c in walk(asyncio.run(board.board("project:16", filter="all", done_limit=50, archived=archived)))}


def client(w) -> TestClient:
    app = FastAPI()
    app.state = w.state
    app.dependency_overrides[require_auth] = lambda: None
    app.include_router(swarm_card_routes.router, prefix="/api/v1")
    return TestClient(app)


def notices_to(w, agent_id: int) -> List[str]:
    return [t["text"] for t in w.told if t["agent"] == agent_id and t.get("source_ref", "").startswith("card_notice:")]


def test_a_card_carries_its_summary_and_an_old_card_falls_back_to_its_first_sentence(world):
    w = world
    cid = make(w, summary="  pick the  dlp vendor  ")
    assert on_board()[cid]["summary"] == "pick the dlp vendor"
    old = call(w, "boss", "swarm_card_create", summary="x", title="old", project_id=16, text="Ship the export first. Then the rest.")["card"]["id"]
    conn = w.huddle._connect(True)
    try:
        conn.execute("UPDATE work_items SET card_summary = '' WHERE id = ?", (old,))
        conn.commit()
    finally:
        conn.close()
    assert on_board()[old]["summary"] == "Ship the export first."
    schema = card_tools.TOOLS["swarm_card_create"]
    assert "summary" in schema[1] and "no file names" in schema[1]["summary"]["description"]
    assert client(w).post("/api/v1/swarm/cards/", json={"title": "t", "project_id": 16}).status_code == 422


def test_the_column_route_pauses_reclassifies_with_a_note_and_marks_done(world):
    w = world
    http = client(w)
    held = dealt_to(w, "fixer", "paused work")
    out = http.post(f"/api/v1/swarm/cards/{held}/column", json={"column": "todo"}).json()
    assert out["column"] == "todo" and out["holder"] is None and not out["queued"]
    out = http.post(f"/api/v1/swarm/cards/{held}/column", json={"column": "in_progress", "note": "use the new schema"}).json()
    assert out["column"] == "in_progress" and out["queued"] and out["owner_note"] == "use the new schema"
    review = dealt_to(w, "builder", "finished work", reason="the paused card waits on the new schema")
    call(w, "builder", "swarm_card_finish", needs_owner=True, owner_ask="check it", card_id=review, result="r", how_to_validate="v")
    assert http.post(f"/api/v1/swarm/cards/{review}/column", json={"column": "done"}).json()["column"] == "done"
    assert http.post(f"/api/v1/swarm/cards/{held}/column", json={"column": "sideways"}).status_code == 422


def test_archive_hides_a_card_behind_the_filter_and_delete_removes_it(world):
    w = world
    http = client(w)
    cid, gone = make(w, "kept"), make(w, "gone")
    assert http.post(f"/api/v1/swarm/cards/{cid}/archive", json={"on": True}).json()["archived_at"] is not None
    assert cid not in on_board() and cid in on_board("only") and cid in on_board("all") and gone not in on_board("only")
    assert http.get("/api/v1/swarm/cards/board", params={"scope": "project:16", "archived": "bogus"}).status_code == 422
    assert http.post(f"/api/v1/swarm/cards/{cid}/archive", json={"on": False}).json()["archived_at"] is None
    assert http.delete(f"/api/v1/swarm/cards/{gone}").json() == {"id": gone, "deleted": True}
    assert gone not in on_board("all") and http.get(f"/api/v1/swarm/cards/{gone}").status_code == 404


def test_the_notice_waits_coalesces_and_says_nothing_when_the_move_is_undone(world):
    w = world
    agent = w.agents["fixer"]["id"]
    held = dealt_to(w, "fixer", "bounced")

    async def bounce():
        await ops.set_column(w.state, held, {"column": "todo"}, by="owner")
        await ops.set_column(w.state, held, {"column": "review"}, by="owner")
        await ops.set_column(w.state, held, {"column": "in_progress"}, by="owner")
        assert notices.pending(held) and not notices_to(w, agent)
        return await notices.flush(w.state, held)

    assert asyncio.run(bounce()) == "unchanged" and not notices_to(w, agent)
    assert asyncio.run(card_port.get().card(held))["holder"]["agent_id"] == agent

    async def pause_twice():
        await ops.set_column(w.state, held, {"column": "review"}, by="owner")
        await ops.set_column(w.state, held, {"column": "todo"}, by="owner")
        return await notices.flush(w.state, held)

    assert asyncio.run(pause_twice()) == "told"
    told = notices_to(w, agent)
    assert len(told) == 1 and "put card" in told[0] and "on hold" in told[0]


def test_a_todo_card_is_never_dealt_and_only_a_flagged_one_is_promoted_when_nothing_is_queued(world):
    w = world
    dealing_step(w)
    plain, flagged = make(w, "plain backlog"), make(w, "flagged backlog")
    assert "not queued" in refused(w, "boss", "swarm_card_deal", card_id=plain, agent_id=w.agents["kid"]["id"])
    queued = make(w, "queued work")
    asyncio.run(ops.set_column(w.state, queued, {"column": "in_progress"}, by="owner"))
    call(w, "boss", "swarm_card_auto_promote", card_id=flagged, on=True)
    w.told.clear()
    assert asyncio.run(dealer.fire(w.state, "16")) == "delivered"
    text = next(t["text"] for t in w.told if t["text"].startswith("Deal request"))
    assert f"card #{queued}:" in text and f"card #{flagged}:" not in text and f"card #{plain}:" not in text
    board_now = on_board()
    assert board_now[flagged]["column"] == "todo" and board_now[flagged]["auto_promote"]
    call(w, "boss", "swarm_card_deal", card_id=queued, agent_id=w.agents["kid"]["id"])
    call(w, "kid", "swarm_card_start", card_id=queued)
    call(w, "kid", "swarm_card_finish", needs_owner=True, owner_ask="check it", card_id=queued, result="r", how_to_validate="v")
    w.told.clear()
    assert asyncio.run(dealer.fire(w.state, "16")) == "delivered"
    text = next(t["text"] for t in w.told if t["text"].startswith("Deal request"))
    board_now = on_board()
    assert board_now[flagged]["column"] == "in_progress" and board_now[flagged]["queued"] and f"card #{flagged}:" in text
    assert board_now[plain]["column"] == "todo" and f"card #{plain}:" not in text
    assert sql_rows(w, "SELECT kind FROM work_card_events WHERE item_id = ? AND kind = 'promoted'", flagged)
