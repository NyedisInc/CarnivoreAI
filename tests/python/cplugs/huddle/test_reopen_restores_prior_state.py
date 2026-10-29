
from __future__ import annotations

from contextlib import closing
from pathlib import Path

import pytest

from src.cplugs.huddle.cards import state_log
from src.cplugs.huddle.store import TaskManagerStore
from src.core.work.storage import WorkStorage


@pytest.fixture
def store(tmp_path: Path) -> TaskManagerStore:
    return TaskManagerStore(WorkStorage(tmp_path), notify=lambda topic: None)


def close_then_reopen(store: TaskManagerStore, prior: str, *, by: str = "joe") -> dict:
    item = store.add("all", "w", actor="joe")["id"]
    if prior != "open":
        store.update(item, actor=by, state=prior)
    store.update(item, actor="joe", approve=True)
    assert store.item(item)["state"] == "done"
    return store.update(item, actor="joe", approve=False)


@pytest.mark.parametrize("prior", ["review", "waiting", "open"])
def test_reopen_restores_the_state_before_the_close(store, prior):
    reopened = close_then_reopen(store, prior)
    assert reopened["state"] == prior


def test_a_task_with_no_state_history_reopens_to_review(store):
    item = store.add("all", "old", actor="joe")["id"]
    store.update(item, actor="joe", approve=True)
    with closing(store._connect(True)) as conn, conn:
        conn.execute("DELETE FROM work_card_events WHERE item_id = ? AND kind = ?", (item, state_log.KIND))
    assert store.update(item, actor="joe", approve=False)["state"] == "review"


def test_a_todo_the_owner_set_comes_back_todo(store):
    assert close_then_reopen(store, "todo", by="joe")["state"] == "todo"


def test_a_todo_an_agent_set_reopens_to_review(store):
    assert close_then_reopen(store, "todo", by="claude")["state"] == "review"


def test_a_reopen_never_lands_on_done(store):
    item = store.add("all", "w", actor="joe")["id"]
    store.update(item, actor="joe", approve=True)
    store.update(item, actor="joe", approve=False)
    store.update(item, actor="joe", approve=True)
    assert store.update(item, actor="joe", approve=False)["state"] != "done"


def test_an_explicit_target_stays_the_owners_choice(store):
    item = store.add("all", "w", actor="joe")["id"]
    store.update(item, actor="joe", approve=True)
    assert store.update(item, actor="joe", state="todo")["state"] == "todo"
