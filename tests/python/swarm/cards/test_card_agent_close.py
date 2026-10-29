
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from src.core.swarm import body
from src.core.swarm.cards import effects, ops, port as card_port
from src.cplugs.huddle import service
from src.cplugs.huddle.cards import policy
from src.cplugs.huddle.cards.port import TaskManagerCardPort
from src.cplugs.sdk.cards import CardRefused
from src.core.work.storage import WorkStorage

WORKER = "agent:9"


@pytest.fixture()
def world(tmp_path: Path, monkeypatch) -> SimpleNamespace:
    policy.drain_kicks()
    ctx = SimpleNamespace(storage=WorkStorage(tmp_path / "huddle"), settings={"view": "area"}, swarm=None, notify=lambda *a, **k: None)
    store = service.store(ctx)
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(
        "CREATE TABLE projects (id INTEGER PRIMARY KEY, display_name TEXT, company_id INTEGER, archived_at TEXT);"
        "CREATE TABLE swarm_agents (id INTEGER PRIMARY KEY, rank TEXT, thread_key TEXT, display_name TEXT, company_id INTEGER,"
        " parent_id INTEGER, task_type TEXT, torn_down_at TEXT);"
        "INSERT INTO projects VALUES (16, 'Zeta', 1, NULL), (17, 'Other', 1, NULL);"
        "INSERT INTO swarm_agents VALUES (5, 'project', '16', 'Zed', 1, NULL, NULL, NULL), (6, 'project', '17', 'Ann', 1, NULL, NULL, NULL),"
        " (9, 'task', 'agent:9', 'Fixer', 1, NULL, NULL, NULL);")

    async def run_db(work: Callable[[sqlite3.Connection], Any]) -> Any:
        return work(db)

    async def no_effects(app_state: Any, items: Any) -> None:
        return None

    monkeypatch.setattr(body, "run_db", run_db)
    monkeypatch.setattr(effects, "run", no_effects)
    card_port.register(TaskManagerCardPort(ctx))
    yield SimpleNamespace(store=store)
    card_port.register(None)


def held_card(store: Any, title: str) -> int:
    card_id = asyncio.run(ops.create(None, None, {"title": title, "project_id": 16, "queued": True}, by="owner",
                                   origin="agent:5"))["id"]
    asyncio.run(card_port.get().act("deal", card_id, {"agent_id": 9}, "owner"))
    asyncio.run(ops.start(None, card_id, {}, by=WORKER))
    return card_id


def finish(card_id: int, **extra: Any) -> dict:
    return asyncio.run(ops.finish(None, card_id, {"result": "built it", "how_to_validate": "run the test", **extra}, by=WORKER))


def test_finish_routes_by_needs_owner_and_close_is_scoped_to_the_closers_project(world):
    done = finish(held_card(world.store, "checked work"), needs_owner=False)
    assert done["column"] == "done"

    asked = finish(held_card(world.store, "mockups"), needs_owner=True, owner_ask="pick mockup a or b")
    assert asked["column"] == "review" and asked["result"].startswith("needs you: pick mockup a or b")
    with pytest.raises(CardRefused) as no_ask:
        finish(held_card(world.store, "no ask"), needs_owner=True)
    assert no_ask.value.code == "bad_card"

    review = finish(held_card(world.store, "legacy report"))
    assert review["column"] == "review"
    with pytest.raises(CardRefused) as other:
        asyncio.run(ops.close(None, review["id"], {"reason": "validated"}, by="agent:6"))
    assert other.value.code == "not_allowed" and card_port_column(review["id"]) == "review"
    with pytest.raises(CardRefused) as worker:
        asyncio.run(ops.close(None, review["id"], {"reason": "validated"}, by=WORKER))
    assert worker.value.code == "not_allowed"
    with pytest.raises(CardRefused) as no_reason:
        asyncio.run(ops.close(None, review["id"], {"reason": " "}, by="agent:5"))
    assert no_reason.value.code == "bad_card"
    closed = asyncio.run(ops.close(None, review["id"], {"reason": "validated by the test run"}, by="agent:5"))
    assert closed["column"] == "done"
    conn = world.store._connect(False)
    event = conn.execute("SELECT by, detail FROM work_card_events WHERE item_id = ? AND kind = 'done'", (review["id"],)).fetchone()
    conn.close()
    assert tuple(event) == ("agent:5", "validated by the test run")

    owners = asyncio.run(ops.create(None, None, {"title": "owner task", "project_id": 16, "queued": True}, by="owner"))["id"]
    asyncio.run(card_port.get().act("deal", owners, {"agent_id": 9}, "owner"))
    asyncio.run(ops.start(None, owners, {}, by=WORKER))
    assert finish(owners, needs_owner=False)["column"] == "review"


def card_port_column(card_id: int) -> str:
    return asyncio.run(card_port.get().card(card_id))["column"]
