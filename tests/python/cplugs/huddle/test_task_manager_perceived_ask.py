
from __future__ import annotations

import pytest

from src.cplugs.huddle import perceived_ask
from src.cplugs.huddle.inbox_store import InboxStore
from src.cplugs.huddle.rules import CLAUDE, JOE, TaskManagerInvalid
from tests.python.cplugs.huddle.test_task_manager_mcp import call, huddle_store, manager  # noqa: F401


def test_the_cleaner_makes_one_bounded_line_and_blank_clears():
    assert perceived_ask.clean_fields(None) == {}
    assert perceived_ask.clean_fields("  make the\nlogin   faster ") == {"perceived_ask": "make the login faster"}
    assert perceived_ask.clean_fields("  ") == {"perceived_ask": None}
    with pytest.raises(TaskManagerInvalid):
        perceived_ask.clean_fields("x" * (perceived_ask.MAX_PERCEIVED_ASK + 1))


def test_an_item_carries_the_perceived_ask_from_add_update_and_the_tool(manager):  # noqa: F811
    store = huddle_store(manager)
    plain = store.add("all", "detail text", actor=JOE)
    assert plain["perceived_ask"] is None and plain["text"] == "detail text"
    assert store.update(plain["id"], actor=JOE, perceived_ask="speed up login")["perceived_ask"] == "speed up login"
    assert store.update(plain["id"], actor=JOE, perceived_ask="")["perceived_ask"] is None
    ok, added = call(manager, "task_manager_add", {"list": "all", "text": "t", "perceived_ask": "one line"})
    assert ok and added["perceived_ask"] == "one line"
    ok, changed = call(manager, "task_manager_update", {"item": added["id"], "perceived_ask": "another"})
    assert ok and changed["perceived_ask"] == "another"


def filed_item(store, inboxes, text="fix login and add dark mode"):
    entry = inboxes.add("all", text)
    item = store.add("all", "fix login", actor=JOE)
    inboxes.link_item(entry["id"], item["id"])
    return entry["id"], store.item(item["id"])


def test_a_fork_links_the_same_original_ask_and_keeps_the_perceived_ask(manager):  # noqa: F811
    store = huddle_store(manager)
    entry, item = filed_item(store, InboxStore(store))
    store.update(item["id"], actor=JOE, perceived_ask="fix login")
    forked = store.fork(item["id"], actor=JOE)["fork"]
    assert forked["from_inbox"] == {"id": entry, "text": "fix login and add dark mode", "direct": False}
    assert forked["perceived_ask"] == "fix login"


def test_a_task_a_session_adds_while_it_works_another_links_that_ones_original_ask(manager):  # noqa: F811
    store = huddle_store(manager)
    entry, parent = filed_item(store, InboxStore(store))
    store.mark_working(parent["id"], "uuid-session-1")
    child = store.add("all", "follow-up", actor=CLAUDE, created_key="uuid-session-1")
    assert child["from_inbox"]["id"] == entry
    stranger = store.add("all", "not mine", actor=CLAUDE, created_key="uuid-session-2")
    assert "from_inbox" not in stranger
    store.update(parent["id"], actor=CLAUDE, state="open")
    assert "from_inbox" not in store.add("all", "later", actor=CLAUDE, created_key="uuid-session-1")
    assert "from_inbox" not in store.add("all", "joe's own", actor=JOE)


def test_rung_39_adds_one_empty_column_and_changes_no_row(tmp_path):
    import sqlite3
    from contextlib import closing

    from tests.python.cplugs.huddle.test_task_manager_lane import synthetic_v37
    from tests.python.cplugs.huddle.test_task_manager_state_rungs import walk

    path = synthetic_v37(tmp_path)
    walk(path, 38)
    with closing(sqlite3.connect(path)) as conn:
        before = [tuple(r) for r in conn.execute("SELECT * FROM items ORDER BY id")]
    walk(path, 39)
    with closing(sqlite3.connect(path)) as conn:
        after = [tuple(r) for r in conn.execute("SELECT * FROM items ORDER BY id")]
    assert before and [row[:-1] for row in after] == before and {row[-1] for row in after} == {None}
