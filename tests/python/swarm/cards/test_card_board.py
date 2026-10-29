
from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import swarm_card_routes
from src.api.auth import require_auth
from src.core.swarm import body
from src.core.swarm.cards import board as card_board, port as card_port
from src.cplugs.huddle import service
from src.cplugs.huddle.cards import policy
from src.cplugs.huddle.cards.port import TaskManagerCardPort
from src.cplugs.huddle.rules import CLAUDE, JOE
from src.cplugs.huddle.store import TaskManagerStore
from src.core.work.storage import WorkStorage


@pytest.fixture()
def world(tmp_path: Path, monkeypatch) -> SimpleNamespace:
    policy.drain_kicks()
    ctx = SimpleNamespace(storage=WorkStorage(tmp_path / "huddle"), settings={"view": "area"}, swarm=None,
                          notify=lambda *a, **k: None)
    store = service.store(ctx)
    app_db = sqlite3.connect(":memory:", check_same_thread=False)
    app_db.row_factory = sqlite3.Row
    app_db.executescript(
        "CREATE TABLE projects (id INTEGER PRIMARY KEY, display_name TEXT, company_id INTEGER, archived_at TEXT);"
        "CREATE TABLE swarm_agents (id INTEGER PRIMARY KEY, rank TEXT, thread_key TEXT, display_name TEXT, company_id INTEGER, torn_down_at TEXT);"
        "INSERT INTO projects VALUES (16, 'Zeta', 1, NULL), (17, 'alpha', 1, NULL), (18, 'Solo', NULL, NULL), (19, 'Old', 1, '2026-01-01');"
        "INSERT INTO swarm_agents VALUES (4, 'task', 'agent:4', 'Loki', NULL, NULL), (7, 'company', 'agent:7', 'Acme HQ', 1, NULL),"
        " (1, 'alpha', 'all', 'SysOp', NULL, NULL);")

    async def run_db(work: Callable[[sqlite3.Connection], Any]) -> Any:
        return work(app_db)

    monkeypatch.setattr(body, "run_db", run_db)
    card_port.register(TaskManagerCardPort(ctx))
    yield SimpleNamespace(store=store, db=app_db)
    card_port.register(None)


def sql(store: TaskManagerStore, query: str, *args: Any) -> None:
    conn = store._connect(True)
    with conn:
        conn.execute(query, args)
    conn.close()


def fill(world: SimpleNamespace) -> SimpleNamespace:
    s = world.store
    ids = SimpleNamespace(
        first=s.add("16", "first in line", actor=JOE)["id"], second=s.add("16", "second in line", actor=JOE)["id"],
        held=s.add("16", "held by loki", actor=JOE)["id"], review=s.add("16", "ready to check", actor=JOE)["id"],
        done=s.add("16", "all finished", actor=JOE)["id"], other=s.add("17", "other project", actor=JOE)["id"],
        shared=s.add("all", "sysop scope card", actor=JOE)["id"], parent=s.add("agent:7", "company parent", actor=JOE)["id"],
        by_agent=s.add("16", "made by an agent", actor=CLAUDE, created_key="sess-x")["id"])
    sql(s, "UPDATE work_items SET card_holder = 4, card_held_since = 9.0, card_parent = ? WHERE id = ?", ids.parent, ids.held)
    sql(s, "UPDATE work_items SET card_origin = 'agent:4' WHERE id = ?", ids.by_agent)
    s.update(ids.review, actor=CLAUDE, state="review")
    s.update(ids.done, actor=CLAUDE, state="review")
    s.update(ids.done, actor=JOE, approve=True)
    s.add("16", "a question", actor=CLAUDE, kind="question")
    return ids


def test_scope_keys_name_each_scopes_queues_and_skip_archived_projects(world):
    assert card_board.scope_list_keys(world.db, "project:16") == [(16, "16")]
    assert card_board.scope_list_keys(world.db, "company:1") == [(17, "17"), (16, "16"), (None, "agent:7")]
    assert card_board.scope_list_keys(world.db, "sysop") == [(17, "17"), (18, "18"), (16, "16"), (None, "all"), (None, "agent:7")]
    with pytest.raises(ValueError):
        card_board.scope_list_keys(world.db, "company:x")


def test_a_project_board_lays_cards_in_columns_in_queue_order_with_counts_win_and_holder_name(world):
    ids = fill(world)
    result = pytest.importorskip("asyncio").run(card_board.board("project:16", filter="all", done_limit=50, now=1e10))
    lane, = result["lanes"]
    assert (lane["project_id"], lane["list_key"], lane["name"]) == (16, "16", "Zeta")
    assert lane["counts"] == {"todo": 3, "in_progress": 1, "review": 1, "done": 1}
    cols = {name: [c["id"] for c in cards] for name, cards in lane["columns"].items()}
    assert cols == {"todo": [ids.first, ids.second, ids.by_agent], "in_progress": [ids.held], "review": [ids.review], "done": [ids.done]}
    assert [c["queue_index"] for c in lane["columns"]["todo"]] == [1, 2, 3]
    held = lane["columns"]["in_progress"][0]
    assert held["holder"] == {"agent_id": 4, "name": "Loki", "since": 9.0, "started_at": None, "beat_at": None} and held["parent"] == ids.parent
    assert lane["rules"]["reorder"] == "suggest" and lane["rules"]["dealing"] is None
    assert result["win"]["in_review"] == 1 and result["win"]["through_review_today"] == 0 and result["capacity"] is None


def test_mine_keeps_top_level_owner_cards_only_and_done_is_cut_to_the_newest(world):
    ids = fill(world)
    run = pytest.importorskip("asyncio").run
    mine = run(card_board.board("project:16", filter="mine", done_limit=50))["lanes"][0]
    assert ids.by_agent not in [c["id"] for c in mine["columns"]["todo"]] and mine["counts"]["todo"] == 2
    assert ids.held not in [c["id"] for c in mine["columns"]["in_progress"]]
    extra = [world.store.add("16", f"done {n}", actor=JOE)["id"] for n in range(3)]
    for item in extra:
        world.store.update(item, actor=JOE, approve=True)
    cut = run(card_board.board("project:16", filter="all", done_limit=2))["lanes"][0]
    assert cut["counts"]["done"] == 4 and [c["id"] for c in cut["columns"]["done"]] == extra[::-1][:2]


def test_company_and_sysop_boards_carry_the_agent_lanes_and_the_win_number_counts_review_to_done_today(world):
    ids = fill(world)
    run = pytest.importorskip("asyncio").run
    company = run(card_board.board("company:1", filter="all", done_limit=50))
    assert [(lane["list_key"], lane["name"]) for lane in company["lanes"]] == [("17", "alpha"), ("16", "Zeta"), ("agent:7", "Acme HQ")]
    assert company["lanes"][2]["counts"]["todo"] == 1 and company["lanes"][2]["project_id"] is None
    sysop = run(card_board.board("sysop", filter="all", done_limit=50))
    assert [lane["list_key"] for lane in sysop["lanes"]][-2:] == ["all", "agent:7"] and sysop["lanes"][-2]["name"] == "SysOp"
    assert company["lanes"][1]["name"] == "Zeta" and run(card_board.board("project:16", filter="all", done_limit=5))["win"]["through_review_today"] == 1
    world.store.update(ids.review, actor=JOE, approve=True)
    won = run(card_board.board("project:16", filter="all", done_limit=50))
    assert won["win"]["through_review_today"] == 2 and won["win"]["in_review"] == 0
    assert run(card_board.board("project:17", filter="all", done_limit=50))["win"]["through_review_today"] == 0
    assert won["win"]["since"] == card_board.local_midnight()
    assert run(card_board.board("company:2", filter="all", done_limit=50))["lanes"] == []


def test_the_routes_answer_the_board_a_card_a_refusal_and_cards_off(world):
    ids = fill(world)
    app = FastAPI()
    app.include_router(swarm_card_routes.router)
    app.dependency_overrides[require_auth] = lambda: None
    client = TestClient(app)
    board = client.get("/swarm/cards/board", params={"scope": "project:16", "done_limit": 5})
    assert board.status_code == 200 and board.json()["lanes"][0]["counts"]["review"] == 1 and board.json()["filter"] == "all"
    one = client.get(f"/swarm/cards/{ids.held}")
    assert one.status_code == 200 and one.json()["holder"]["name"] == "Loki" and one.json()["column"] == "in_progress"
    assert client.get(f"/swarm/cards/{ids.first}").json()["queue_index"] == 1
    for bad in ({"scope": "project:0"}, {"scope": "everything"}, {"filter": "some"}, {"done_limit": 0}, {"done_limit": 501}):
        assert client.get("/swarm/cards/board", params=bad).status_code == 422
    question = world.store.add("16", "asking", actor=CLAUDE, kind="question")["id"]
    refused = client.get(f"/swarm/cards/{question}")
    assert refused.status_code == 404 and refused.json()["detail"]["code"] == "not_a_card"
    assert client.get("/swarm/cards/999999").status_code == 404
    card_port.register(None)
    off = client.get("/swarm/cards/board")
    assert off.status_code == 409 and off.json()["detail"]["code"] == "cards_off"
    app.dependency_overrides.clear()
    assert client.get("/swarm/cards/board").status_code in (401, 403)


def test_the_events_route_answers_a_cards_history_oldest_first_and_refuses_a_non_card(world):
    ids = fill(world)
    app = FastAPI()
    app.include_router(swarm_card_routes.router)
    app.dependency_overrides[require_auth] = lambda: None
    client = TestClient(app)
    done = client.get(f"/swarm/cards/{ids.done}/events")
    assert done.status_code == 200 and done.json()["card_id"] == ids.done
    rows = done.json()["events"]
    assert [(e["kind"], e["to_col"]) for e in rows] == [("created", "todo"), ("moved", "review"), ("done", "done")]
    assert rows[0]["by"] == "owner" and rows[-1]["from_col"] == "review"
    ats = [e["at"] for e in done.json()["events"]]
    assert ats == sorted(ats) and {"at", "kind", "from_col", "to_col", "by", "detail"} <= set(done.json()["events"][-1])
    assert all(e["kind"] != "done" for e in client.get(f"/swarm/cards/{ids.first}/events").json()["events"])
    question = world.store.add("16", "asking", actor=CLAUDE, kind="question")["id"]
    assert client.get(f"/swarm/cards/{question}/events").status_code == 404
    assert client.get("/swarm/cards/999999/events").status_code == 404
    app.dependency_overrides.clear()
    assert client.get(f"/swarm/cards/{ids.done}/events").status_code in (401, 403)


def test_the_event_window_route_caps_the_window_truncates_to_the_newest_and_keeps_the_scope(world, monkeypatch):
    import time
    ids = fill(world)
    app = FastAPI()
    app.include_router(swarm_card_routes.router)
    app.dependency_overrides[require_auth] = lambda: None
    client = TestClient(app)
    now = time.time()
    since, until = now - 3600, now + 60
    sysop = client.get("/swarm/cards/events", params={"scope": "sysop", "since": since, "until": until})
    assert sysop.status_code == 200 and sysop.json()["truncated"] is False
    rows = sysop.json()["events"]
    assert {"item_id", "list_key", "at", "kind", "from_col", "to_col", "by"} == set(rows[0])
    assert [r["at"] for r in rows] == sorted(r["at"] for r in rows)
    assert {ids.first, ids.other, ids.done, ids.by_agent} <= {r["item_id"] for r in rows}
    assert any(r["item_id"] == ids.done and r["to_col"] == "done" for r in rows)
    p17 = client.get("/swarm/cards/events", params={"scope": "project:17", "since": since, "until": until}).json()["events"]
    assert p17 and {r["item_id"] for r in p17} == {ids.other} and {r["list_key"] for r in p17} == {"17"}
    mine = client.get("/swarm/cards/events", params={"scope": "project:16", "filter": "mine", "since": since, "until": until}).json()["events"]
    assert ids.by_agent not in {r["item_id"] for r in mine} and ids.first in {r["item_id"] for r in mine}
    assert client.get("/swarm/cards/events", params={"scope": "sysop", "since": now + 30, "until": until}).json()["events"] == []
    over = client.get("/swarm/cards/events", params={"scope": "sysop", "since": now - 8 * 86400 - 1, "until": now})
    assert over.status_code == 422 and over.json()["detail"]["code"] == "bad_window"
    assert client.get("/swarm/cards/events", params={"scope": "sysop", "since": now, "until": now}).status_code == 422
    assert client.get("/swarm/cards/events", params={"scope": "sysop", "since": now - 8 * 86400, "until": now}).status_code == 200
    monkeypatch.setattr(swarm_card_routes, "EVENT_WINDOW_ROWS", 3)
    cut = client.get("/swarm/cards/events", params={"scope": "sysop", "since": since, "until": until}).json()
    assert cut["truncated"] is True and cut["events"] == rows[-3:]
    app.dependency_overrides.clear()
    assert client.get("/swarm/cards/events", params={"since": since, "until": until}).status_code in (401, 403)
