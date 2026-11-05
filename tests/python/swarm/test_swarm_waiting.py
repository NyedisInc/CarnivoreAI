
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from src.core.swarm import waiting
from src.core.swarm.views import AgentMissing

AGENTS = [
    {"id": 1, "parent_id": None, "rank": "alpha", "thread_key": "agent:1", "session_row_id": 11, "display_name": "sysop"},
    {"id": 2, "parent_id": 1, "rank": "company", "thread_key": "agent:2", "session_row_id": 12, "display_name": "co"},
    {"id": 3, "parent_id": 2, "rank": "project", "thread_key": "agent:3", "session_row_id": 13, "display_name": "proj"},
    {"id": 4, "parent_id": None, "rank": "company", "thread_key": "agent:4", "session_row_id": 14, "display_name": "other"},
]


def test_scope_is_the_root_and_every_descendant() -> None:
    assert waiting.scope_ids(AGENTS, 1) == [1, 2, 3]
    assert waiting.scope_ids(AGENTS, 2) == [2, 3]
    assert waiting.scope_ids(AGENTS, 4) == [4]


def test_only_a_review_card_finished_with_needs_owner_waits() -> None:
    assert waiting.needs_owner({"column": "review", "result": "needs you: pick a mockup\n\nbody"})
    assert not waiting.needs_owner({"column": "review", "result": "landed and live"})
    assert not waiting.needs_owner({"column": "done", "result": "needs you: pick"})


def test_own_items_first_then_oldest_first() -> None:
    items = [{"agent_id": 3, "at": 5}, {"agent_id": 1, "at": 9}, {"agent_id": 2, "at": 1}]
    assert [(i["agent_id"], i["at"]) for i in waiting.order(items, 1)] == [(1, 9), (2, 1), (3, 5)]


class _Inbox:
    async def list_items(self) -> List[Dict[str, Any]]:
        return [{"id": "dlg:a", "session_id": "ses_proj", "kind": "permission", "question": "edit a file?", "created_at": 100},
                {"id": "dlg:b", "session_id": "ses_stranger", "kind": "permission", "question": "x", "created_at": 50}]


class _Manager:
    async def list_session_infos(self) -> List[Any]:
        return [SimpleNamespace(session_row_id=13, host_key=None, session=SimpleNamespace(id="ses_proj")),
                SimpleNamespace(session_row_id=99, host_key=None, session=SimpleNamespace(id="ses_stranger"))]


class _Cards:
    async def cards(self, *, columns: Any = ()) -> List[Dict[str, Any]]:
        return [{"id": 7, "column": "review", "result": "needs you: pick one", "last_holder": 2, "updated_at": 10},
                {"id": 8, "column": "review", "result": "needs you: other company", "last_holder": 4, "updated_at": 1},
                {"id": 9, "column": "review", "result": "done", "holder": {"agent_id": 3}, "updated_at": 1}]


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run_db(fn: Any) -> Any:
        if fn is waiting.store.list_agents:
            return [dict(a) for a in AGENTS]
        return fn(None)

    async def cards_none(rows: Any, ids: Any) -> List[Dict[str, Any]]:
        return [{"kind": "card", "id": "card:x", "agent_id": 1, "author_path": [{"name": "sysop"}], "at": 200.0, "entry": {}}] if 1 in ids else []

    monkeypatch.setattr(waiting.body, "run_db", run_db)
    monkeypatch.setattr(waiting, "chains_of", lambda conn: None)
    monkeypatch.setattr(waiting, "_card_items", cards_none)
    monkeypatch.setattr(waiting.card_port, "get", lambda: _Cards())
    monkeypatch.setattr(waiting.author_path, "path_for_agent", lambda conn, row: [{"name": row["display_name"]}])


def test_feed_rolls_up_descendants_and_leaves_strangers_out(wired: None) -> None:
    found = asyncio.run(waiting.feed(1, manager=_Manager(), inbox=_Inbox()))
    assert [i["id"] for i in found["items"]] == ["card:x", "review:7", "approval:dlg:a"]
    assert found["count"] == 3
    assert found["items"][2]["author_path"] == [{"name": "proj"}]
    assert waiting.brief(found["items"][1])["ask"] == "pick one"


def test_feed_of_a_leaf_is_its_own_items_only(wired: None) -> None:
    found = asyncio.run(waiting.feed(3, manager=_Manager(), inbox=_Inbox()))
    assert [i["id"] for i in found["items"]] == ["approval:dlg:a"]


def test_unknown_agent_is_missing(wired: None) -> None:
    with pytest.raises(AgentMissing):
        asyncio.run(waiting.feed(42, manager=_Manager(), inbox=None))


def test_scope_follows_the_escalation_chain_past_a_missing_parent_link() -> None:
    rows = [{"id": 1}, {"id": 122}, {"id": 45}, {"id": 7}]
    chains = {1: [], 122: [1], 45: [122, 1], 7: [1]}
    assert waiting.scope_ids(rows, 122, chains) == [122, 45]
    assert waiting.scope_ids(rows, 1, chains) == [1, 7, 122, 45]
    assert waiting.scope_ids(rows, 45, chains) == [45]


class _Threads:
    async def open_cards(self) -> List[Dict[str, Any]]:
        return [{"id": 1729, "thread_key": "agent:122", "kind": "question", "swarm_ref": "question:16"},
                {"id": 1730, "thread_key": "agent:122", "kind": "question", "swarm_ref": "promotion:3"}]


def test_a_question_escalated_to_the_owner_is_a_tray_item_on_the_askers_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = {45: {"id": 45, "thread_key": "54"}, 122: {"id": 122, "thread_key": "agent:122"}}
    question = {"id": "item:1729", "kind": "card", "waits_on_owner": True, "at": "2026-11-02T22:57:18Z",
                "author_path": [{"kind": "project", "name": "Home", "agent_id": 45}],
                "item": {"swarm_ref": "question:16", "state": "open"},
                "question": {"summary": "pick one", "askers": [{"agent_id": 45, "name": "Dispatcher"}]}}
    promotion = {"id": "item:1730", "kind": "card", "waits_on_owner": True, "at": "2026-11-02T22:58:00Z", "author_path": [],
                 "item": {"swarm_ref": "promotion:3", "state": "open"}}
    read: List[str] = []

    async def card_entries(agent: Dict[str, Any], item_ids: List[int]) -> List[Dict[str, Any]]:
        read.append(agent["thread_key"])
        return [e for e in (question, promotion) if int(e["id"].split(":")[1]) in item_ids]

    async def run_db(fn: Any) -> Any:
        return {16: {45}}

    monkeypatch.setattr(waiting.thread_port, "get", lambda: _Threads())
    monkeypatch.setattr(waiting.stream, "card_entries", card_entries)
    monkeypatch.setattr(waiting.body, "run_db", run_db)
    mine = asyncio.run(waiting._card_items(rows, [45]))
    assert [(i["id"], i["agent_id"]) for i in mine] == [("card:item:1729", 45)]
    assert read == ["agent:122"]
    rolled = asyncio.run(waiting._card_items(rows, [122, 45]))
    assert sorted((i["id"], i["agent_id"]) for i in rolled) == [("card:item:1729", 45), ("card:item:1730", 122)]


def test_every_card_that_spikes_a_node_is_a_tray_item_and_nothing_else_is(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.swarm import alerts, owner_wait, stream

    agents = [{"id": n, "thread_key": f"agent:{n}"} for n in range(1, 10)]
    rows = {a["id"]: a for a in agents}
    posted = [
        (1, "question", "promotion:1", "question"), (2, "waiting", "naming:2", "waiting"), (3, "info", "stuck:3:ab", "open"),
        (4, "info", "alert:immediate:x", "open"), (5, "question", "question:7", "question"), (6, "question", "question:8", "question"),
        (7, "info", "wake_refused:7:1", "open"), (8, "info", "stuck:99:ab", "open"), (9, "done", "report:9", "open")]
    live = {7: {5}}
    alive = {a["id"] for a in agents}
    open_cards = [{"id": 100 + n, "thread_key": f"agent:{n}", "kind": kind, "swarm_ref": ref, "title": ref, "text": ref}
                  for n, kind, ref, _st in posted]
    chatter = [{"kind": "agent", "id": f"msg:{i}", "at": 2_000_000.0 + i, "text": "hi"} for i in range(300)]

    class Port:
        async def open_cards(self) -> List[Dict[str, Any]]:
            return open_cards

        async def read_thread(self, key: str, limit: int, *, cards: bool = True) -> List[Dict[str, Any]]:
            n = int(key.split(":")[1])
            mine = [{"kind": "card", "id": f"item:{100 + c}", "at": 1.0, "item": {"swarm_ref": ref, "kind": kind, "state": "open",
                     "status": st, "thread": []}} for c, kind, ref, st in posted if c == n]
            return (mine + chatter)[-limit:]

    async def run_db(fn: Any) -> Any:
        return fn(None)

    monkeypatch.setattr(owner_wait, "live_questions", lambda _c: live)
    monkeypatch.setattr(owner_wait, "live_agent_ids", lambda _c: alive)
    monkeypatch.setattr(stream.author_path, "annotate", lambda *_a: None)
    monkeypatch.setattr(waiting.thread_port, "get", lambda: Port())
    monkeypatch.setattr(stream.thread_port, "get", lambda: Port())
    monkeypatch.setattr(waiting.body, "run_db", run_db)
    monkeypatch.setattr(stream.body, "run_db", run_db)
    monkeypatch.setattr("src.core.mcp.tools.redact_text", lambda t: t)
    spiked = {a for a, v in alerts.derive(open_cards, agents, live).items() if v["alert"]}
    tray = {i["agent_id"] for i in asyncio.run(waiting._card_items(rows, list(rows)))}
    assert spiked == {1, 2, 3, 4, 5}
    assert tray == spiked
