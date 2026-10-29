
from __future__ import annotations

import asyncio
import json
import time
from contextlib import closing

import pytest

from src.core.crosstalk import store as crosstalk_store
from src.core.db import connect, db_path_for
from src.core.mcp import card_tools, tools
from src.core.mcp.common import ToolError
from src.core.swarm import facts
from src.core.swarm.cards import ops
from tests.python.swarm.cards.test_card_enforcement import call, col, refused, sql_rows, world  # noqa: F401

BAD = {"detail": False}


def _dealt(w, slug="fixer", title="work"):
    card = call(w, "boss", "swarm_card_create", summary="a plain line", title=title, project_id=16)["card"]
    asyncio.run(ops.set_column(w.state, card["id"], {"column": "in_progress"}, by="owner"))
    call(w, "boss", "swarm_card_deal", card_id=card["id"], agent_id=w.agents[slug]["id"])
    return card["id"]


def _insert_message(w, receiver: str, status: str, text: str) -> None:
    now = time.time()
    with closing(connect(db_path_for(w.tmp / "state"), create=False)) as conn:
        conn.execute("INSERT INTO crosstalk_messages (id, thread, sender_key, receiver_key, sender_id, receiver_id, sender_name, sender_provider, text,"
                     " status, created_at, expires_at) VALUES (?, 't', 'peer-key', ?, 'p', 'r', 'Peer', 'claude', ?, ?, ?, ?)",
                     (f"m-{text}-{status}", receiver, text, status, now, now + 3600))
        conn.commit()


def test_start_answers_the_full_card_and_a_count_never_peer_text(world, monkeypatch):
    w = world
    card = _dealt(w)
    for status in ("queued", "held", "delivered"):
        _insert_message(w, "key-fixer", status, f"SECRET PEER REQUEST {status}")
    _insert_message(w, "key-other", "queued", "not for fixer")
    monkeypatch.setattr(card_tools.crosstalk_bus, "caller_identity", lambda view, c: _async({"key": "key-fixer"}))
    started = call(w, "fixer", "swarm_card_start", card_id=card)
    assert started["unread_peer_messages"] == 2
    assert started["card"]["column"] == "in_progress" and started["card"]["holder"]["agent_id"] == w.agents["fixer"]["id"]
    assert {"how_to_validate", "handoff", "children", "summary"} <= set(started["card"])
    assert "SECRET PEER REQUEST" not in json.dumps(started) and "peer-key" not in json.dumps(started)


def test_start_survives_an_unreadable_pane_identity(world, monkeypatch):
    w = world
    card = _dealt(w)

    async def boom(view, c):
        raise ToolError("your authenticated pane is no longer listed")

    monkeypatch.setattr(card_tools.crosstalk_bus, "caller_identity", boom)
    started = call(w, "fixer", "swarm_card_start", card_id=card)
    assert started["card"]["column"] == "in_progress" and "unread_peer_messages" not in started


async def _async(value):
    return value


def _started(w, slug="fixer", title="work"):
    cid = _dealt(w, slug, title)
    call(w, slug, "swarm_card_start", card_id=cid)
    return cid


def test_finish_writes_the_facts_first_then_finishes(world, monkeypatch):
    w = world
    cid = _started(w)
    order = []

    async def remember(view, c, fact):
        order.append(("remember", fact["title"], sql_rows(w, "SELECT state FROM work_items WHERE id = ?", cid)[0][0]))
        return {"fact_id": f"f_{fact['title']}", "state": "live", "origin": "agent", "scope": fact["scope"]}

    monkeypatch.setattr(facts, "remember", remember)
    done = call(w, "fixer", "swarm_card_finish", needs_owner=True, owner_ask="check it", card_id=cid, result="r", how_to_validate="v", **BAD,
                remember=[{"title": "a", "scope": "craft", "text": "x"}, {"title": "b", "scope": "project", "text": "y"}])
    assert order == [("remember", "a", "open"), ("remember", "b", "open")]
    assert col(w, cid) == "review" and done["card"]["column"] == "review"
    assert [r["fact_id"] for r in done["remembered"]] == ["f_a", "f_b"]


def test_finish_with_a_failed_fact_does_not_finish(world, monkeypatch):
    w = world
    cid = _started(w)

    async def remember(view, c, fact):
        raise facts.FactRefused("the fact could not be written; try again")

    monkeypatch.setattr(facts, "remember", remember)
    text = refused(w, "fixer", "swarm_card_finish", needs_owner=True, owner_ask="check it", card_id=cid, result="r", how_to_validate="v", remember={"title": "a", "scope": "craft", "text": "x"})
    assert "NOT finished" in text and "could not be written" in text
    assert col(w, cid) == "in_progress"
    assert "remember must be" in refused(w, "fixer", "swarm_card_finish", needs_owner=True, owner_ask="check it", card_id=cid, result="r", how_to_validate="v", remember="nope")


def test_finish_refused_after_the_facts_were_written_reports_both(world, monkeypatch):
    w = world
    cid = _started(w)

    async def remember(view, c, fact):
        return {"fact_id": "f_kept", "state": "live", "origin": "agent", "scope": "craft"}

    monkeypatch.setattr(facts, "remember", remember)
    text = refused(w, "fixer", "swarm_card_finish", needs_owner=True, owner_ask="check it", card_id=cid, result="r", how_to_validate="   ", remember={"title": "a", "scope": "craft", "text": "x"})
    assert "no_how_to_validate" in text and "f_kept" in text and "were written" in text
    assert col(w, cid) == "in_progress"


def test_finish_without_remember_is_today_s_finish(world):
    w = world
    cid = _started(w)
    done = call(w, "fixer", "swarm_card_finish", needs_owner=True, owner_ask="check it", card_id=cid, result="r", how_to_validate="v", **BAD)
    assert "remembered" not in done and done["card"]["column"] == "review"


def test_create_takes_a_list_with_per_item_errors_and_still_takes_one_card(world):
    w = world
    made = call(w, "boss", "swarm_card_create", project_id=16, **BAD, cards=[
        {"title": "one", "summary": "s1"}, {"title": "no summary"}, {"title": "three", "summary": "s3", "queued": True}])
    assert [c["title"] for c in made["created"]] == ["one", "three"]
    assert [c["column"] for c in made["created"]] == ["todo", "in_progress"]
    assert set(made["created"][0]) == {"id", "title", "column", "revision"}
    assert len(made["errors"]) == 1 and made["errors"][0]["index"] == 1 and "summary" in made["errors"][0]["error"]
    single = call(w, "boss", "swarm_card_create", title="solo", summary="s", project_id=16, **BAD)
    assert set(single["card"]) == {"id", "title", "column", "revision"}
    assert "either cards or" in refused(w, "boss", "swarm_card_create", title="t", summary="s", project_id=16, cards=[{"title": "x", "summary": "y"}])
    assert "1 to 20" in refused(w, "boss", "swarm_card_create", project_id=16, cards=[{"title": f"c{i}", "summary": "s"} for i in range(21)])
    assert "1 to 20" in refused(w, "boss", "swarm_card_create", project_id=16, cards=[])


def test_a_list_keeps_the_gate_of_each_item(world):
    w = world
    made = call(w, "fixer", "swarm_card_create", project_id=16, cards=[{"title": "loose", "summary": "s"}])
    assert made["created"] == [] and "child cards of the card it holds" in made["errors"][0]["error"]


def test_card_writes_answer_lean_and_detail_returns_the_full_card(world):
    w = world
    cid = _started(w)
    lean = call(w, "fixer", "swarm_card_handoff", card_id=cid, handoff="half", progress=40, **BAD)["card"]
    assert set(lean) == {"id", "column", "title", "revision", "changed"} and lean["id"] == cid and lean["column"] == "in_progress"
    assert {"handoff", "progress"} <= set(lean["changed"]) and "revision" not in lean["changed"] and "holder" not in lean["changed"]
    full = call(w, "fixer", "swarm_card_handoff", card_id=cid, handoff="more", progress=50, detail=True)["card"]
    assert full["handoff"] == "more" and "how_to_validate" in full and full["revision"] > lean["revision"]
    fin = call(w, "fixer", "swarm_card_finish", needs_owner=True, owner_ask="check it", card_id=cid, result="r", how_to_validate="v", **BAD)["card"]
    assert fin["column"] == "review" and "column" in fin["changed"] and "result" in fin["changed"]
    assert "true or false" in refused(w, "fixer", "swarm_card_release", card_id=cid, reason="r", detail="yes")


def test_list_pages_with_has_more_and_next_and_lean_rows(world):
    w = world
    ids = [call(w, "boss", "swarm_card_create", title=f"c{i}", summary="s", project_id=16, **BAD)["card"]["id"] for i in range(5)]
    first = call(w, "boss", "swarm_card_list", project_id=16, limit=2, detail=False)
    assert [c["id"] for c in first["cards"]] == ids[:2] and first["has_more"] is True and first["next"] == 2
    assert set(first["cards"][0]) <= set(card_tools._LIST_KEYS) | {"holder"} and "text" not in first["cards"][0] and "handoff" not in first["cards"][0]
    second = call(w, "boss", "swarm_card_list", project_id=16, limit=2, offset=first["next"], detail=False)
    last = call(w, "boss", "swarm_card_list", project_id=16, limit=2, offset=second["next"], detail=False)
    assert [c["id"] for c in second["cards"] + last["cards"]] == ids[2:] and last["has_more"] is False and last["next"] is None
    full = call(w, "boss", "swarm_card_list", project_id=16, limit=1, detail=True)
    assert "text" in full["cards"][0] and "handoff" in full["cards"][0]


def test_no_tool_was_added_and_the_name_keyed_sets_are_unchanged():
    assert set(card_tools.TOOLS) == {"swarm_card_list", "swarm_card_get", "swarm_card_board", "swarm_card_create", "swarm_card_start", "swarm_card_handoff",
                                     "swarm_card_finish", "swarm_card_close", "swarm_card_release", "swarm_card_reorder", "swarm_card_deal", "swarm_card_queue",
                                     "swarm_card_auto_promote", "swarm_card_archive", "swarm_card_delete"}
    assert card_tools.TOOLS["swarm_card_create"][2] == []
    for name in ("swarm_card_create", "swarm_card_finish", "swarm_card_start"):
        assert name in tools.WRITE_TOOLS
