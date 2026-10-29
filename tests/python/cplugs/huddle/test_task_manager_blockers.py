
from __future__ import annotations

import sqlite3
from contextlib import closing

from src.cplugs.huddle import blockers
from src.cplugs.huddle.blockers import BlockerStore
from src.cplugs.huddle.rules import JOE
from tests.python.cplugs.huddle.test_task_manager_lane import synthetic_v37
from tests.python.cplugs.huddle.test_task_manager_mcp import huddle_store, manager  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_state_rungs import walk


def test_rung_40_adds_an_empty_table_and_changes_no_row(tmp_path):
    path = synthetic_v37(tmp_path)
    walk(path, 39)
    with closing(sqlite3.connect(path)) as conn:
        before = [tuple(r) for r in conn.execute("SELECT * FROM items ORDER BY id")]
    walk(path, 40)
    with closing(sqlite3.connect(path)) as conn:
        assert [tuple(r) for r in conn.execute("SELECT * FROM items ORDER BY id")] == before
        assert conn.execute("SELECT COUNT(*) FROM blockers").fetchone()[0] == 0
        assert [r[1] for r in conn.execute("PRAGMA table_info(blockers)")] == [
            "id", "item_id", "kind", "text", "evidence", "created_by", "created_at", "cleared_by", "cleared_at"]


def test_a_hold_is_shown_on_the_item_and_cleared_without_losing_the_row(manager):  # noqa: F811
    store = huddle_store(manager)
    item = store.add("all", "split the build", actor=JOE)
    assert "blockers" not in item
    store.fork(item["id"], actor="claude", claimed_by="uuid-s1", parent_waits=True)
    shown = store.item(item["id"])
    assert [(b["kind"], b["text"], b["holding"], b["created_by"]) for b in shown["blockers"]] == [("children", blockers.HOLD_TEXT, 1, "uuid-s1")]
    assert shown["revision"] > item["revision"]
    with closing(store._connect(True)) as conn, conn:
        assert blockers.set_hold(conn, item["id"], by="someone", now=1.0) == shown["blockers"][0]["id"]
        assert blockers.clear_all(conn, item["id"], by="joe", now=2.0) == 1
        assert blockers.clear_all(conn, item["id"], by="someone-else", now=3.0) == 0
    assert "blockers" not in store.item(item["id"])
    kept = BlockerStore(store).for_item(item["id"], include_cleared=True)
    assert [(b["cleared_by"], b["cleared_at"]) for b in kept] == [("joe", 2.0)]
    assert BlockerStore(store).for_item(item["id"]) == []


def test_the_kinds_the_rung_named_stay_readable(manager):  # noqa: F811
    assert blockers.CHILDREN in blockers.KINDS and set(blockers.HOLDING_STATES) == {"open", "waiting"}
