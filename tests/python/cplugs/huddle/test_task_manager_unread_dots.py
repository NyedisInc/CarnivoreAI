
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.core.work.storage import WorkStorage
from src.core.work.work_ladder import VERSION as WORK_VERSION
from src.cplugs.huddle.store import TaskManagerStore

DAILY = {"freq": "daily", "time": "09:00"}


@pytest.fixture
def store(tmp_path: Path) -> TaskManagerStore:
    return TaskManagerStore(WorkStorage(tmp_path), notify=lambda _key: None)


def dot(store: TaskManagerStore, item: int) -> bool:
    return store.item(item)["unread"]


def raw(store: TaskManagerStore, item: int, column: str) -> int:
    with closing(store._connect(False)) as conn:
        return conn.execute(f"SELECT {column} FROM work_items WHERE id = ?", (item,)).fetchone()[0]


def test_an_agent_task_is_born_read(store):
    item = store.add("all", "agent made", actor="claude")["id"]
    assert dot(store, item) is False
    assert store.add("all", "owner made", actor="joe")["unread"] is False


def test_an_agent_task_born_with_a_question_a_review_or_a_notify_info_is_unread(store):
    asked = store.add("all", "asks", actor="claude")["id"]
    store.post(asked, "which one?", actor="claude", kind="question")
    reviewed = store.add("all", "reviews", actor="claude")["id"]
    store.update(reviewed, actor="claude", state="review")
    told = store.add("all", "tells", actor="claude")["id"]
    store.post(told, "look at this", actor="claude", kind="info", notify=True)
    quiet = store.add("all", "quiet info", actor="claude")["id"]
    store.post(quiet, "fyi", actor="claude", kind="info")
    assert [dot(store, i) for i in (asked, reviewed, told, quiet)] == [True, True, True, False]


def test_a_swarm_lane_item_keeps_its_born_unread_rule(store):
    item = store.add("all", "swarm made", actor="claude", created_key="swarm")["id"]
    assert dot(store, item) is True


def _repeating_review(store: TaskManagerStore) -> int:
    when = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    item = store.add("12", "sweep", actor="joe", fire_at=when, repeat=DAILY)["id"]
    store.update(item, actor="claude", state="review")
    assert dot(store, item) is True
    return item


def test_the_owners_tick_of_a_repeating_item_clears_its_dot(store):
    item = _repeating_review(store)
    ticked = store.update(item, actor="joe", approve=True)
    assert ticked["state"] == "open" and ticked["unread"] is False


def test_the_owners_tick_clears_the_dot_of_a_plain_item(store):
    item = store.add("all", "work", actor="claude")["id"]
    store.update(item, actor="claude", state="review")
    assert dot(store, item) is True
    assert store.update(item, actor="joe", approve=True)["unread"] is False


def test_reading_the_last_unread_card_clears_the_dot(store):
    item = store.add("all", "work", actor="joe")["id"]
    first = store.post(item, "one", actor="claude", kind="info", notify=True)["message"]["id"]
    second = store.post(item, "two", actor="claude", kind="info", notify=True)["message"]["id"]
    assert store.mark_seen(item, first)["unread"] is True
    assert store.mark_seen(item, second)["unread"] is False


def test_reading_one_card_keeps_the_dot_of_an_unanswered_question(store):
    item = store.add("all", "work", actor="joe")["id"]
    info = store.post(item, "fyi", actor="claude", kind="info", notify=True)["message"]["id"]
    store.post(item, "which?", actor="claude", kind="question")
    assert store.mark_seen(item, info)["unread"] is True


def _stale(store: TaskManagerStore, item: int) -> None:
    with closing(store._connect(True)) as conn, conn:
        seq = store._next_seq(conn)
        conn.execute("UPDATE work_items SET attention_seq = ? WHERE id = ?", (seq, item))
    assert dot(store, item) is True


def test_the_startup_sweep_clears_only_dots_no_card_backs(store):
    parked = store.add("all", "parked", actor="joe", state="todo")["id"]
    _stale(store, parked)
    asking = store.add("all", "asking", actor="joe")["id"]
    store.post(asking, "which?", actor="claude", kind="question")
    unread_card = store.add("all", "has a card", actor="joe")["id"]
    store.post(unread_card, "look", actor="claude", kind="info", notify=True)
    review = store.add("all", "in review", actor="claude")["id"]
    store.update(review, actor="claude", state="review")
    swarm = store.add("all", "swarm", actor="claude", created_key="swarm")["id"]
    gone = store.add("all", "deleted", actor="joe")["id"]
    _stale(store, gone)
    store.delete(gone, actor="joe")
    with closing(store._connect(False)) as conn:
        version = conn.execute("SELECT v FROM work_meta WHERE k = 'work_ladder'").fetchone()[0]

    assert store.sweep_stale_dots() == [parked]
    assert store.sweep_stale_dots() == []
    assert [dot(store, i) for i in (parked, asking, unread_card, review, swarm)] == [False, True, True, True, True]
    assert raw(store, gone, "attention_seq") > raw(store, gone, "seen_seq")
    with closing(store._connect(False)) as conn:
        assert conn.execute("SELECT v FROM work_meta WHERE k = 'work_ladder'").fetchone()[0] == version == WORK_VERSION
