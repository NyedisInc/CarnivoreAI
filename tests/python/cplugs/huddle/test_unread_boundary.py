
from __future__ import annotations

from contextlib import closing
from pathlib import Path

import pytest

from src.cplugs.huddle.rules import TaskManagerInvalid
from src.cplugs.huddle.store import TaskManagerStore
from src.core.work.storage import WorkStorage


@pytest.fixture
def store(tmp_path: Path) -> TaskManagerStore:
    return TaskManagerStore(WorkStorage(tmp_path), notify=lambda _key: None)


def _unread(item: dict) -> list:
    return [m["text"] for m in item["thread"] if m["unread"]]


def _joe_seq(store: TaskManagerStore, item: int) -> int:
    with closing(store._connect(False)) as conn:
        return conn.execute("SELECT joe_seq FROM work_items WHERE id = ?", (item,)).fetchone()[0]


def _item_with_attention(store: TaskManagerStore) -> tuple:
    item = store.add("all", "work", actor="joe")["id"]
    shown = store.post(item, "drawn by the client", actor="claude", kind="attention")["message"]["id"]
    return item, shown


def test_a_message_arriving_during_a_reply_stays_unread_after_the_reply_saves(store):
    item, shown = _item_with_attention(store)
    store.post(item, "arrived while the owner typed", actor="claude", kind="attention")
    done = store.post(item, "my reply", actor="joe", ack_through=shown)["item"]
    assert _unread(done) == ["arrived while the owner typed"]
    assert done["unread"] is True
    assert store.item(item)["unread"] is True


def test_a_reply_reads_everything_up_to_the_boundary_and_clears_the_dot(store):
    item, shown = _item_with_attention(store)
    done = store.post(item, "my reply", actor="joe", ack_through=shown)["item"]
    assert _unread(done) == [] and done["unread"] is False


def test_a_reply_with_no_boundary_reads_all_there_is(store):
    item, _shown = _item_with_attention(store)
    assert store.post(item, "my reply", actor="joe")["item"]["unread"] is False


def test_a_failed_save_keeps_everything_unread(store, monkeypatch):
    item, shown = _item_with_attention(store)

    def boom(*_args, **_kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr("src.cplugs.huddle.store.sends.stamp_joe", boom)
    with pytest.raises(RuntimeError):
        store.post(item, "my reply", actor="joe", ack_through=shown)
    monkeypatch.undo()
    after = store.item(item)
    assert _unread(after) == ["drawn by the client"] and after["unread"] is True
    assert [m["text"] for m in after["thread"] if m["author"] == "joe"] == []


def test_a_boundary_that_is_not_on_the_item_is_refused_and_changes_nothing(store):
    item, _shown = _item_with_attention(store)
    other = store.add("all", "other", actor="joe")["id"]
    foreign = store.post(other, "elsewhere", actor="claude", kind="attention")["message"]["id"]
    with pytest.raises(TaskManagerInvalid):
        store.post(item, "my reply", actor="joe", ack_through=foreign)
    assert store.item(item)["unread"] is True


def test_a_comment_acknowledges_nothing_and_is_never_sent(store):
    item, _shown = _item_with_attention(store)
    store.post(item, "q?", actor="claude", kind="question")
    before, joe_before = store.item(item), _joe_seq(store, item)
    posted = store.post(item, "a quiet note", actor="joe", kind="comment")
    after = posted["item"]
    assert posted["message"]["kind"] == "comment" and posted["message"]["quiet"] is True
    assert _unread(after) == _unread(before) and after["unread"] is True
    assert after["state"] == before["state"] and after["status"] == before["status"]
    assert _joe_seq(store, item) == joe_before, "nothing for a tell to carry"
    assert [m["answered"] for m in after["thread"] if m["kind"] == "question"] == [False]


def test_a_comment_does_not_reopen_a_closed_task(store):
    item = store.add("all", "work", actor="joe")["id"]
    store.update(item, actor="joe", state="done")
    store.post(item, "late note", actor="joe", kind="comment")
    assert store.item(item)["state"] == "done"


def test_opening_acknowledges_nothing_but_mark_read_does(store):
    item, shown = _item_with_attention(store)
    later = store.post(item, "later", actor="claude", kind="attention")["message"]["id"]
    store.item(item)
    assert store.item(item)["unread"] is True
    marked = store.mark_seen(item, through=shown)
    assert _unread(marked) == ["later"] and marked["unread"] is True
    assert store.mark_seen(item, through=later)["unread"] is False


def test_changing_state_reads_nothing_and_a_tick_acknowledges(store):
    item, _shown = _item_with_attention(store)
    store.update(item, actor="joe", state="review")
    after = store.item(item)
    assert after["unread"] is True and _unread(after) == ["drawn by the client"]
    store.update(item, actor="joe", state="done")
    after = store.item(item)
    assert after["unread"] is False and _unread(after) == []


def test_an_unread_answer_to_his_message_keeps_needing_him_until_acknowledged(store):
    item = store.add("all", "work", actor="joe")["id"]
    asked = store.post(item, "ship friday?", actor="joe")["message"]["id"]
    store.post(item, "yes", actor="claude", kind="answer", quote=asked)
    assert store.item(item)["needs_you"] is True
    store.update(item, actor="joe", state="review")
    assert store.item(item)["needs_you"] is True
    answer = [m for m in store.item(item)["thread"] if m["kind"] == "answer"][0]["id"]
    assert store.mark_seen(item, through=answer)["needs_you"] is False
