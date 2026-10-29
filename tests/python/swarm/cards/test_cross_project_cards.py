
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List

import pytest

from src.core.swarm import body
from src.core.swarm.cards import board as card_board, effects, ops, permits, port as card_port
from src.cplugs.huddle import service
from src.cplugs.huddle.cards import policy
from src.cplugs.huddle.cards.port import TaskManagerCardPort
from src.cplugs.sdk.cards import CardRefused
from src.cplugs.huddle.rules import CLAUDE, JOE
from src.core.work.storage import WorkStorage

COMPANY_1 = {"id": 7, "rank": "company", "thread_key": "agent:7", "company_id": 1}
COMPANY_2 = {"id": 8, "rank": "company", "thread_key": "agent:8", "company_id": 2}
ALPHA = {"id": 1, "rank": "alpha", "thread_key": "all", "company_id": None}


@pytest.fixture()
def world(tmp_path: Path, monkeypatch) -> SimpleNamespace:
    policy.drain_kicks()
    ctx = SimpleNamespace(storage=WorkStorage(tmp_path / "huddle"), settings={"view": "area"}, swarm=None, notify=lambda *a, **k: None)
    store = service.store(ctx)
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(
        "CREATE TABLE projects (id INTEGER PRIMARY KEY, display_name TEXT, company_id INTEGER, archived_at TEXT);"
        "CREATE TABLE swarm_agents (id INTEGER PRIMARY KEY, rank TEXT, thread_key TEXT, display_name TEXT, company_id INTEGER, torn_down_at TEXT);"
        "INSERT INTO projects VALUES (16, 'Zeta', 1, NULL), (17, 'alpha', 1, NULL), (20, 'Other', 2, NULL);"
        "INSERT INTO swarm_agents VALUES (5, 'project', '16', 'Zed', 1, NULL), (6, 'project', '17', 'Ann', 1, NULL),"
        " (7, 'company', 'agent:7', 'Acme HQ', 1, NULL), (8, 'company', 'agent:8', 'Other HQ', 2, NULL), (1, 'alpha', 'all', 'SysOp', NULL, NULL);")

    async def run_db(work: Callable[[sqlite3.Connection], Any]) -> Any:
        return work(db)

    async def no_effects(app_state: Any, items: Any) -> None:
        return None

    monkeypatch.setattr(body, "run_db", run_db)
    monkeypatch.setattr(effects, "run", no_effects)
    card_port.register(TaskManagerCardPort(ctx))
    yield SimpleNamespace(store=store)
    card_port.register(None)


def sql(store: Any, query: str, *args: Any) -> None:
    conn = store._connect(True)
    with conn:
        conn.execute(query, args)
    conn.close()


def card(card_id: int) -> Dict[str, Any]:
    return asyncio.run(card_port.get().card(card_id))


def lane(board: Dict[str, Any], key: str) -> Dict[str, Any]:
    return next(ln for ln in board["lanes"] if ln["list_key"] == key)


def where(board: Dict[str, Any], key: str, card_id: int) -> List[str]:
    return [name for name, cards in lane(board, key)["columns"].items() for c in cards if c["id"] == card_id]


def board(scope: str, filter: str = "all") -> Dict[str, Any]:
    return asyncio.run(card_board.board(scope, filter=filter, done_limit=50))


def accept(child: int, by_agent: int) -> List[Dict[str, Any]]:
    port = card_port.get()
    result = asyncio.run(port.act("accept_child", child, {"by_agent": by_agent, "report_id": child}, f"agent:{by_agent}"))
    for effect in result["effects"]:
        if effect["kind"] == "rollup":
            asyncio.run(port.act("rollup", int(effect["card_id"]), {}, "server"))
    return result["effects"]


def test_company_parent_with_children_in_two_projects(world):
    s = world.store
    parent = s.add("agent:7", "launch the new line", actor=JOE)["id"]
    kid16 = s.add("16", "16 part", actor=JOE)["id"]
    kid17 = s.add("17", "17 part", actor=JOE)["id"]
    for kid in (kid16, kid17):
        sql(s, "UPDATE work_items SET card_parent = ? WHERE id = ?", parent, kid)

    for key in ("16", "17"):
        assert permits.can_create(COMPANY_1, key, card(parent), company_id=1) is None
    assert "may not make cards" in permits.can_create(COMPANY_1, "20", card(parent), company_id=2)
    assert "only under its own cards" in permits.can_create(COMPANY_2, "20", card(parent), company_id=2), "company 2 may not hang children on company 1's card"
    assert permits.can_create(ALPHA, "20", card(parent), company_id=2) is None
    in_project = {"list_key": "16", "project_id": 16}
    assert permits.can_create(COMPANY_1, "17", in_project, company_id=1, parent_company_id=1) is None
    assert permits.can_create(COMPANY_1, "17", in_project, company_id=1, parent_company_id=2)
    project_5, project_6 = {"id": 5, "rank": "project", "thread_key": "16"}, {"id": 6, "rank": "project", "thread_key": "17"}
    assert permits.check(project_5, "deal", card(kid16), {}, company_id=1) is None
    assert permits.check(project_5, "deal", card(kid17), {}, company_id=1)
    assert permits.can_create(project_5, "16", card(parent), company_id=1)
    assert permits.can_create(project_5, "16", {"list_key": "17", "project_id": 17}, company_id=1, parent_company_id=1)
    assert permits.can_create(project_5, "16", {"list_key": "20", "project_id": 20}, company_id=1, parent_company_id=2)
    assert permits.can_create(project_5, "16", {"list_key": "16", "project_id": 16}, company_id=1, parent_company_id=1) is None
    assert permits.check(project_6, "deal", card(kid17), {}, company_id=1) is None

    for scope in ("company:1", "sysop"):
        b = board(scope)
        assert where(b, "agent:7", parent) == ["todo"]
        assert where(b, "16", parent) == ["todo"] and where(b, "17", parent) == ["todo"]
        assert [c["lane_role"] for c in lane(b, "16")["columns"]["todo"] if c["id"] == parent] == ["parent_of_children_here"]
        assert [c["lane_role"] for c in lane(b, "agent:7")["columns"]["todo"] if c["id"] == parent] == [None]
        assert [c["queue_index"] for c in lane(b, "16")["columns"]["todo"] if c["id"] == parent] == [None]
        assert lane(b, "16")["counts"]["todo"] == 2
    assert where(board("project:16"), "16", parent) == []
    assert where(board("company:2"), "20", parent) == []
    assert where(board("company:1", "mine"), "16", parent) == ["todo"]
    sysop_parent = s.add("all", "company-wide push", actor=JOE)["id"]
    sql(s, "UPDATE work_items SET card_parent = ? WHERE id = ?", sysop_parent, kid16)
    assert where(board("company:1"), "16", sysop_parent) == ["todo"] and where(board("company:1"), "agent:7", sysop_parent) == []
    sql(s, "UPDATE work_items SET card_parent = ? WHERE id = ?", parent, kid16)

    for kid in (kid16, kid17):
        s.update(kid, actor=CLAUDE, state="review")
    assert card(kid16)["column"] == "review"
    assert accept(kid16, 5) == [] and card(parent)["column"] != "review"
    assert [e["kind"] for e in accept(kid17, 6)] == ["rollup"]
    rolled = card(parent)
    assert rolled["column"] == "review" and "2 of 2 done" in rolled["how_to_validate"]
    b = board("company:1")
    assert [where(b, k, parent) for k in ("agent:7", "16", "17")] == [["review"]] * 3

    asyncio.run(card_port.get().act("done", parent, {}, "owner"))
    assert [card(i)["state"] for i in (parent, kid16, kid17)] == ["done"] * 3
    assert all(where(board("company:1"), k, parent) == ["done"] for k in ("agent:7", "16", "17"))


def test_create_resolves_the_parents_company_and_foreign_parents_stay_off_the_board(world):
    s = world.store
    own = s.add("16", "company 1 card", actor=JOE)["id"]
    other = s.add("20", "company 2 card", actor=JOE)["id"]
    sysop_card = s.add("all", "company-wide push", actor=JOE)["id"]

    made = asyncio.run(ops.create(None, None, {"title": "17 part", "project_id": 17, "parent": own}, by="agent:7"))
    assert made["list_key"] == "17" and made["parent"] == own
    with pytest.raises(CardRefused) as refused:
        asyncio.run(ops.create(None, None, {"title": "bad", "project_id": 17, "parent": other}, by="agent:7"))
    assert refused.value.code == "not_allowed"
    with pytest.raises(CardRefused):
        asyncio.run(ops.create(None, None, {"title": "bad", "project_id": 16, "parent": made["id"]}, by="agent:5"))

    kid = s.add("16", "kid", actor=JOE)["id"]
    sql(s, "UPDATE work_items SET card_parent = ? WHERE id = ?", other, kid)
    assert where(board("company:1"), "16", other) == []
    assert where(board("sysop"), "20", other) == ["todo"] and where(board("sysop"), "16", other) == ["todo"]
    sql(s, "UPDATE work_items SET card_parent = ? WHERE id = ?", sysop_card, kid)
    assert where(board("company:1"), "16", sysop_card) == ["todo"]
