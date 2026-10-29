
from __future__ import annotations

from pathlib import Path

import pytest

from src.cplugs.huddle.store import TaskManagerStore
from src.core.work.storage import WorkStorage


@pytest.fixture
def store(tmp_path: Path) -> TaskManagerStore:
    return TaskManagerStore(WorkStorage(tmp_path), notify=lambda _key: None)


def _park(store: TaskManagerStore, waiting_on: str, kind: str = "person") -> int:
    item = store.add("all", "blocked work", actor="joe")["id"]
    store.update(item, actor="claude", state="waiting", wait={"waiting_on": waiting_on, "wait_kind": kind}, wait_by="u-1")
    return item


def test_a_reply_on_a_wait_that_is_not_on_the_owner_keeps_it_waiting(store):
    item = _park(store, "the vendor's invoice", "vendor")
    done = store.post(item, "any news?", actor="joe", kind="reply")["item"]
    assert done["state"] == "waiting" and done["wait"]["waiting_on"] == "the vendor's invoice"


def test_a_reply_on_a_wait_that_names_the_owner_releases_it(store):
    item = _park(store, "Joe runs the handoff script", "install")
    assert store.post(item, "confirmed", actor="joe", kind="reply")["item"]["state"] == "open"


def test_a_comment_never_releases_even_a_wait_on_the_owner(store):
    item = _park(store, "Joe runs the handoff script", "install")
    assert store.post(item, "note to self", actor="joe", kind="comment")["item"]["state"] == "waiting"
