
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.cplugs.huddle import service
from src.cplugs.huddle.store import TaskManagerStore
from src.core.work.ladder import MIGRATIONS, SCHEMA_VERSION
from src.core.work.storage import WorkStorage
from tests.python.cplugs.huddle.test_task_manager_mcp import call, huddle_store, manager  # noqa: F401


@pytest.fixture(autouse=True)
def two_projects(monkeypatch):
    monkeypatch.setattr(service, "project_names", lambda ctx: {"12": "Carnivore", "7": "Blog"})


def test_rung_25_upgrades_an_old_file_and_old_rows_read_null(tmp_path: Path):
    path = tmp_path / "huddle.db"
    with sqlite3.connect(path) as conn:
        for step in MIGRATIONS[:24]:
            conn.executescript(step)
        conn.execute("INSERT INTO items (list_key, text, position, created_by, state, created_at, updated_at, created_seq, seq) "
                     "VALUES ('all', 'old', 0, 'joe', 'open', 1, 1, 1, 1)")
        conn.execute("PRAGMA user_version = 24")
    item = TaskManagerStore(WorkStorage(path.parent), notify=lambda t: None).list_items("all")["items"][0]
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        cols = {r[1] for r in conn.execute("PRAGMA table_info(items)")}
        assert {"from_project_id", "from_project_name"} <= cols
    assert item["from_project"] is None


def test_cross_project_add_is_tagged_and_an_own_add_is_not(manager):
    ok, mine = call(manager, "task_manager_add", {"list": "12", "text": "mine"})
    assert ok and "from_project" not in mine
    ok, theirs = call(manager, "task_manager_add", {"list": "7", "text": "for blog", "cross_project": True})
    assert ok and theirs["cross_project"] == {"from": "Carnivore", "to": "Blog"}
    assert huddle_store(manager).item(theirs["id"])["from_project"] == {"id": "12", "name": "Carnivore"}
    assert huddle_store(manager).item(mine["id"])["from_project"] is None


def test_first_cross_project_writer_wins_and_a_reply_tags_only_an_untagged_item(manager):
    store = huddle_store(manager)
    untagged = store.add("7", "blog work", actor="joe")["id"]
    ok, _ = call(manager, "task_manager_reply", {"item": untagged, "text": "hi", "kind": "info", "cross_project": True})
    assert ok and store.item(untagged)["from_project"] == {"id": "12", "name": "Carnivore"}
    assert store.stamp_from_project(untagged, "99", "Other") is False
    assert store.item(untagged)["from_project"]["id"] == "12"
