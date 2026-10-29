
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.cplugs.huddle import actor_log, service
from src.cplugs.huddle.store import TaskManagerStore
from src.core.work.ladder import MIGRATIONS, SCHEMA_VERSION
from src.core.work.storage import WorkStorage
from tests.python.cplugs.huddle.test_task_manager_mcp import call, huddle_store, manager  # noqa: F401


@pytest.fixture(autouse=True)
def two_projects(monkeypatch):
    monkeypatch.setattr(service, "project_names", lambda ctx: {"12": "Carnivore", "7": "Blog"})


def test_rung_31_upgrades_an_old_file_and_old_rows_have_no_actors(tmp_path: Path):
    path = tmp_path / "huddle.db"
    with sqlite3.connect(path) as conn:
        for step in MIGRATIONS[:30]:
            conn.executescript(step)
        conn.execute("INSERT INTO items (list_key, text, position, created_by, state, created_at, updated_at, created_seq, seq) "
                     "VALUES ('all', 'old', 0, 'joe', 'open', 1, 1, 1, 1)")
        conn.execute("PRAGMA user_version = 30")
    store = TaskManagerStore(WorkStorage(path.parent), notify=lambda t: None)
    old = store.list_items("all")["items"][0]
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert "source_item_id" in {r[1] for r in conn.execute("PRAGMA table_info(items)")}
    assert actor_log.actors_of(store, old["id"]) == {"item_id": old["id"], "source_item_id": None, "actors": []}


def test_add_update_reply_ask_and_move_each_record_the_acting_session(manager):
    store = huddle_store(manager)
    ok, item = call(manager, "task_manager_add", {"list": "12", "text": "work"})
    assert ok
    assert call(manager, "task_manager_update", {"item": item["id"], "state": "review"})[0]
    assert call(manager, "task_manager_reply", {"item": item["id"], "text": "note", "kind": "info"})[0]
    assert call(manager, "task_manager_ask", {"item": item["id"], "text": "which one?"})[0]
    assert call(manager, "task_manager_move", {"item": item["id"], "list": "all"})[0]
    log = actor_log.actors_of(store, item["id"])["actors"]
    assert [row["op"] for row in log] == ["add", "update", "reply", "ask", "move"]
    assert {row["actor_session_id"] for row in log} == {"ses_1"}
    assert all(row["actor_key"] for row in log) and not any(row["cross_project"] for row in log)


def test_a_refused_write_records_nothing(manager):
    store = huddle_store(manager)
    ok, _ = call(manager, "task_manager_add", {"list": "7", "text": "blog"})
    assert not ok
    with store._connect(False) as conn:
        assert conn.execute("SELECT COUNT(*) FROM work_write_actors").fetchone()[0] == 0


def test_cross_project_add_links_the_single_item_the_writer_holds_working(manager):
    store = huddle_store(manager)
    ok, mine = call(manager, "task_manager_add", {"list": "12", "text": "my task"})
    assert call(manager, "task_manager_update", {"item": mine["id"], "state": "working"})[0]
    ok, theirs = call(manager, "task_manager_add", {"list": "7", "text": "for blog", "cross_project": True})
    assert ok
    got = actor_log.actors_of(store, theirs["id"])
    assert got["source_item_id"] == mine["id"] and got["actors"][0]["cross_project"] is True
    assert actor_log.actors_of(store, mine["id"])["source_item_id"] is None


def test_no_link_when_the_writer_holds_no_item_or_two(manager):
    store = huddle_store(manager)
    ok, bare = call(manager, "task_manager_add", {"list": "7", "text": "no source", "cross_project": True})
    assert actor_log.actors_of(store, bare["id"])["source_item_id"] is None
    for text in ("one", "two"):
        _, held = call(manager, "task_manager_add", {"list": "12", "text": text})
        call(manager, "task_manager_update", {"item": held["id"], "state": "working"})
    _, ambiguous = call(manager, "task_manager_add", {"list": "7", "text": "which?", "cross_project": True})
    assert actor_log.actors_of(store, ambiguous["id"])["source_item_id"] is None
    assert actor_log.link_source(store, ambiguous["id"], ambiguous["id"]) is False


def test_card_event_actor_is_the_session_inside_a_guarded_write_and_claude_outside():
    import asyncio

    assert actor_log.by_for("claude") == "claude" and actor_log.by_for("joe") == "owner"
    token = actor_log.set_acting_key("sess-key-1")
    try:
        assert asyncio.run(asyncio.to_thread(actor_log.by_for, "claude")) == "sess-key-1"
        assert actor_log.by_for("joe") == "owner"
    finally:
        actor_log.reset_acting_key(token)
    assert actor_log.by_for("claude") == "claude"


def test_the_item_wire_carries_the_source_link(manager):
    store = huddle_store(manager)
    _, mine = call(manager, "task_manager_add", {"list": "12", "text": "my task"})
    call(manager, "task_manager_update", {"item": mine["id"], "state": "working"})
    _, theirs = call(manager, "task_manager_add", {"list": "7", "text": "mirror", "cross_project": True})
    assert store.item(theirs["id"])["source_item_id"] == mine["id"]
    assert store.item(mine["id"])["source_item_id"] is None
