
from __future__ import annotations

from pathlib import Path

import pytest

from src.cplugs.huddle import lifecycle
from src.cplugs.huddle.store import TaskManagerStore
from src.core.work.storage import WorkStorage


@pytest.fixture
def store(tmp_path: Path) -> TaskManagerStore:
    return TaskManagerStore(WorkStorage(tmp_path), notify=lambda _key: None)


def _lines(item: dict) -> list:
    return [m["text"] for m in item["thread"] if m.get("category") == "status"]


def test_an_unread_info_puts_the_item_in_needs_you_until_marked_read(store):
    item = store.add("all", "work", actor="joe")["id"]
    before = store.item(item)["status"]
    posted = store.post(item, "fyi, found a snag", actor="claude", kind="info")
    now = store.item(item)
    assert now["needs_you"] is True and now["needs_action"] == "read"
    assert now["status"] == before
    store.mark_seen(item, message_id=posted["message"]["id"])
    after = store.item(item)
    assert after["needs_you"] is False and after["needs_action"] is None


def test_a_status_change_takes_the_item_out_of_needs_you_without_reading_the_info(store):
    item = store.add("all", "work", actor="joe")["id"]
    store.post(item, "fyi", actor="claude", kind="info")
    assert store.item(item)["needs_you"] is True
    moved = store.update(item, actor="claude", state="review")
    assert moved["needs_you"] is False
    assert moved["info_unread"] == 1


def test_an_info_after_the_status_change_needs_him_again(store):
    item = store.add("all", "work", actor="joe")["id"]
    store.update(item, actor="claude", state="review")
    store.update(item, actor="joe", state="open")
    store.post(item, "second fyi", actor="claude", kind="info")
    assert store.item(item)["needs_you"] is True


def test_the_status_line_is_never_unread_and_never_needs_him(store):
    item = store.add("all", "work", actor="joe")["id"]
    store.update(item, actor="claude", state="review")
    now = store.item(item)
    assert now["needs_you"] is False and now["info_unread"] == 0 and now["attention_unread"] == 0


def test_every_state_move_leaves_one_line_saying_who_from_to(store):
    item = store.add("all", "work", actor="joe")["id"]
    assert _lines(store.item(item)) == []
    store.update(item, actor="claude", state="review")
    store.update(item, actor="joe", state="open")
    lines = _lines(store.item(item))
    assert len(lines) == 2
    assert "open to review" in lines[0] and "agent" in lines[0]
    assert "review to open" in lines[1] and "owner" in lines[1]
    line = [m for m in store.item(item)["thread"] if m.get("category") == "status"][0]
    assert line["created_at"] > 0 and line["unread"] is False


def test_an_owner_reply_that_reopens_a_review_logs_the_move_and_the_task_still_awaits_the_answer(store):
    from contextlib import closing
    from src.cplugs.huddle import reply_return

    item = store.add("all", "work", actor="joe")["id"]
    store.update(item, actor="claude", state="review")
    store.post(item, "one more thing", actor="joe")
    assert any("review to open" in t for t in _lines(store.item(item)))
    with closing(store._connect(False)) as conn:
        assert reply_return.answered_since_reply(conn, item) is False


def test_a_no_op_write_adds_no_line(store):
    item = store.add("all", "work", actor="joe")["id"]
    store.update(item, actor="joe", text="reworded")
    assert _lines(store.item(item)) == []


def test_a_working_claim_and_a_question_marked_answered_leave_lines_too(store):
    item = store.add("all", "work", actor="joe")["id"]
    store.mark_working(item, "sess-1")
    assert any("to working by an agent" in t for t in _lines(store.item(item)))
    store.post(item, "which one?", actor="claude", kind="question")
    store.mark_answered(item, actor="joe")
    assert _lines(store.item(item))[-1].endswith("from question to open by the owner")
    store.mark_working(item, "sess-1")
    store.mark_working(item, "sess-1")
    assert sum("to working" in t for t in _lines(store.item(item))) == 2


def test_point_15_new_and_reopened_tasks_land_open_and_the_agent_moves_them_on(store):
    item = store.add("all", "work", actor="claude")["id"]
    assert store.item(item)["state"] == "open"
    store.update(item, actor="claude", state="review")
    assert store.post(item, "one more thing", actor="joe")["item"]["state"] == "open"
    store.update(item, actor="joe", approve=True)
    assert store.update(item, actor="joe", approve=False)["state"] == "open"
    assert store.update(item, actor="claude", state="todo")["state"] == "todo"
    lines = _lines(store.item(item))
    assert any("to open by the owner" in t for t in lines) and any("to todo by an agent" in t for t in lines)
