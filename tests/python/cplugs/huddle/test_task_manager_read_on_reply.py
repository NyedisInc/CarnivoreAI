
from __future__ import annotations

from pathlib import Path

import pytest

from src.cplugs.huddle.store import TaskManagerStore
from src.core.work.storage import WorkStorage


@pytest.fixture
def pushed() -> list:
    return []


@pytest.fixture
def store(tmp_path: Path, pushed: list) -> TaskManagerStore:
    return TaskManagerStore(WorkStorage(tmp_path), notify=pushed.append)


def _unread(item: dict) -> list:
    return [m["text"] for m in item["thread"] if m["unread"]]


def test_a_reply_reads_every_unread_claude_post_including_later_ones(store, pushed):
    item = store.add("all", "work", actor="joe")["id"]
    store.post(item, "early info", actor="claude", kind="info")
    store.post(item, "early look", actor="claude", kind="attention")
    store.post(item, "which one?", actor="claude", kind="question")
    store.post(item, "late info", actor="claude", kind="info")
    pushed.clear()
    done = store.post(item, "the first", actor="joe")["item"]
    assert _unread(done) == []
    assert done["info_unread"] == 0 and done["attention_unread"] == 0
    assert pushed, "the list topic is pushed so every window drops the posts"


def test_a_reply_with_no_open_question_reads_the_infos_too(store):
    item = store.add("all", "work", actor="joe")["id"]
    store.post(item, "just an info", actor="claude", kind="info")
    assert _unread(store.post(item, "ok", actor="joe")["item"]) == []


def test_a_post_after_a_reply_stays_unread(store):
    item = store.add("all", "work", actor="joe")["id"]
    store.post(item, "q1", actor="claude", kind="question")
    store.post(item, "answer", actor="joe")
    store.post(item, "newer info", actor="claude", kind="info")
    assert _unread(store.item(item)) == ["newer info"]


def test_ticking_an_item_acknowledges_it(store):
    item = store.add("all", "work", actor="joe")["id"]
    store.post(item, "a look", actor="claude", kind="attention")
    store.post(item, "an info", actor="claude", kind="info")
    other = store.add("all", "other", actor="joe")["id"]
    store.post(other, "other info", actor="claude", kind="info")
    assert store.item(item)["unread"] is True
    ticked = store.update(item, actor="joe", approve=True)
    assert _unread(ticked) == [] and ticked["unread"] is False
    assert ticked["info_unread"] == 0 and ticked["attention_unread"] == 0
    assert _unread(store.item(other)) == ["other info"]


def test_a_non_approving_edit_reads_nothing(store):
    item = store.add("all", "work", actor="joe")["id"]
    store.post(item, "an info", actor="claude", kind="info")
    assert _unread(store.update(item, actor="joe", text="work, edited")) == ["an info"]


def test_a_reply_reads_a_claude_note_of_any_kind_too(store):
    from contextlib import closing

    item = store.add("all", "work", actor="joe")["id"]
    store.post(item, "an info", actor="claude", kind="info")
    with closing(store._connect(True)) as conn, conn:
        conn.execute("INSERT INTO work_messages (item_id, author, kind, text, created_at, seq, author_key, parts) "
                     "VALUES (?, 'claude', 'reply', 'an old note', 1.0, 999, '', '')", (item,))

    def seen() -> list:
        with closing(store._connect(False)) as conn:
            return [r[0] for r in conn.execute("SELECT seen FROM work_messages WHERE item_id = ? ORDER BY id", (item,))]

    assert seen() == [0, 0]
    store.post(item, "ok", actor="joe")
    assert seen()[:2] == [1, 1]
