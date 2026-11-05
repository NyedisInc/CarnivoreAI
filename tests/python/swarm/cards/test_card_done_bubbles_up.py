
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from src.core.mcp import swarm_tools
from src.core.swarm import body, done_feed, stream, views
from src.core.swarm.cards import effects, ops, port as card_port
from src.core.work.storage import WorkStorage
from src.cplugs.huddle import service
from src.cplugs.huddle.cards import policy
from src.cplugs.huddle.cards.port import TaskManagerCardPort

WORKER = "agent:9"
AGENTS = {"sysop": {"id": 1, "rank": "alpha", "thread_key": "all", "company_id": None},
          "company": {"id": 8, "rank": "company", "thread_key": "agent:8", "company_id": 1},
          "project": {"id": 5, "rank": "project", "thread_key": "16", "company_id": 1},
          "task": {"id": 9, "rank": "task", "thread_key": "agent:9", "company_id": 1}}


@pytest.fixture()
def world(tmp_path: Path, monkeypatch) -> SimpleNamespace:
    policy.drain_kicks()
    storage = WorkStorage(tmp_path / "huddle")
    ctx = SimpleNamespace(storage=storage, settings={"view": "area"}, swarm=None, notify=lambda *a, **k: None)
    service.store(ctx)
    storage.ensure_ready()
    db = sqlite3.connect(storage.db_path, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(
        "CREATE TABLE projects (id INTEGER PRIMARY KEY, display_name TEXT, company_id INTEGER, archived_at TEXT);"
        "CREATE TABLE swarm_agents (id INTEGER PRIMARY KEY, rank TEXT, thread_key TEXT, display_name TEXT, company_id INTEGER,"
        " parent_id INTEGER, task_type TEXT, torn_down_at TEXT);"
        "INSERT INTO projects VALUES (16, 'Zeta', 1, NULL);"
        "INSERT INTO swarm_agents VALUES (1, 'alpha', 'all', 'SysOp', NULL, NULL, NULL, NULL), (8, 'company', 'agent:8', 'Nyedis', 1, NULL, NULL, NULL),"
        " (5, 'project', '16', 'Zed', 1, NULL, NULL, NULL), (9, 'task', 'agent:9', 'Fixer', 1, NULL, NULL, NULL);")
    db.commit()

    async def run_db(work: Callable[[sqlite3.Connection], Any]) -> Any:
        return work(db)

    async def no_effects(app_state: Any, items: Any) -> None:
        return None

    monkeypatch.setattr(body, "run_db", run_db)
    monkeypatch.setattr(effects, "run", no_effects)
    card_port.register(TaskManagerCardPort(ctx))
    yield SimpleNamespace(db=db)
    card_port.register(None)
    db.close()


def worked(title: str, **extra: Any) -> int:
    card_id = asyncio.run(ops.create(None, None, {"title": title, "summary": f"{title} for the owner", "project_id": 16, "queued": True, **extra},
                                     by="owner", origin="agent:5"))["id"]
    asyncio.run(card_port.get().act("deal", card_id, {"agent_id": 9}, "owner"))
    asyncio.run(ops.start(None, card_id, {}, by=WORKER))
    asyncio.run(ops.finish(None, card_id, {"result": "built it", "how_to_validate": "run the test", "needs_owner": False}, by=WORKER))
    return card_id


def lines(agent: str) -> list:
    return [(e["card_id"], e["text"]) for e in asyncio.run(done_feed.done_entries(AGENTS[agent], 200))]


def test_tasks_reach_the_project_chat_features_reach_project_company_and_sysop_once_each(world, monkeypatch):
    feature = worked("login remembers you")
    small = worked("fix a typo", level="task")
    child = worked("split part", parent=feature)
    if asyncio.run(card_port.get().card(child))["column"] != "done":
        asyncio.run(card_port.get().act("done", child, {}, "owner"))

    assert asyncio.run(card_port.get().card(feature))["level"] == "feature"
    assert asyncio.run(card_port.get().card(child))["level"] == "task"
    assert asyncio.run(card_port.get().card(small))["level"] == "task"
    assert sorted(lines("project")) == sorted([(feature, "Fixer: login remembers you for the owner, done"),
                                               (small, "Fixer: fix a typo for the owner, done"), (child, "Fixer: split part for the owner, done")])
    assert lines("company") == lines("sysop") == [(feature, "Fixer: login remembers you for the owner, done")]
    assert lines("task") == []
    assert done_feed.done_entries in stream.EXTRA_SOURCES

    assert sorted(done_feed.upward_agents(world.db, "16")) == [1, 8]
    assert done_feed.upward_agents(world.db, "16") == []

    async def page(agent: dict, **_: Any) -> dict:
        return {"entries": await done_feed.done_entries(agent, 200) + [{"kind": "agent", "id": "msg:1", "at": 0.0, "text": "hi"}], "cursor": "msg:1"}

    async def row(agent_id: int) -> dict:
        return AGENTS["sysop"]

    monkeypatch.setattr(stream, "page", page)
    monkeypatch.setattr(views, "get_agent_row", row)
    read = asyncio.run(swarm_tools.swarm_conversation(None, None, {"agent_id": 1}))
    assert '"done"' not in json.dumps(read) and "msg:1" in json.dumps(read)
