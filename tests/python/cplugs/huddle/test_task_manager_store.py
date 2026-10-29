
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.cplugs.huddle import rules
from src.cplugs.huddle.rules import TaskManagerForbidden, TaskManagerInvalid, TaskManagerNotFound, TaskManagerStale
from src.cplugs.huddle.store import TaskManagerStore
from src.core.work.ladder import MIGRATIONS, SCHEMA_VERSION
from src.core.work.importer import ready
from src.core.work.storage import WorkStorage
from src.core.work.work_ladder import VERSION as WORK_VERSION
from src.cplugs.sdk import CplugSchemaError


@pytest.fixture
def pushed() -> list:
    return []


@pytest.fixture
def store(tmp_path: Path, pushed: list) -> TaskManagerStore:
    return TaskManagerStore(WorkStorage(tmp_path), notify=pushed.append)


def test_a_read_never_creates_the_file(tmp_path: Path):
    store = TaskManagerStore(WorkStorage(tmp_path), notify=lambda t: None)
    assert store.list_items("all")["items"] == []
    assert store.changes(0)["cursor"] == 0
    assert not (tmp_path / "huddle.db").exists()


def test_add_appends_marks_the_author_and_pushes_the_list_topic(store, pushed):
    a = store.add("all", "fix this", actor="joe")
    b = store.add("all", "done: the tab", actor="claude")
    assert [i["id"] for i in store.list_items("all")["items"]] == [a["id"], b["id"]]
    assert (a["created_by"], b["created_by"]) == ("joe", "claude")
    assert a["state"] == b["state"] == "open"
    assert pushed == ["all", "all"]
    store.add("12", "per project", actor="joe")
    assert pushed[-1] == "12"


def test_claude_marks_done_and_joe_approves_with_and_without_a_note(store):
    item = store.add("all", "done: x", actor="claude")
    item = store.update(item["id"], actor="claude", state="review")
    assert item["state"] == "review"
    item = store.update(item["id"], actor="joe", approve=True)
    assert item["state"] == "done"
    item = store.update(item["id"], actor="joe", note="good, but rename it")
    assert item["state"] == "done"
    item = store.update(item["id"], actor="joe", note="")
    assert item["state"] == "done"
    item = store.update(item["id"], actor="joe", approve=False)
    assert item["state"] == "review"


def test_claude_can_never_approve_nor_undo_an_approval(store):
    item = store.add("all", "x", actor="claude")
    with pytest.raises(TaskManagerForbidden):
        store.update(item["id"], actor="claude", approve=True)
    with pytest.raises(TaskManagerForbidden):
        store.update(item["id"], actor="claude", state="done")
    with pytest.raises(TaskManagerForbidden):
        store.update(item["id"], actor="claude", state="done")
    store.update(item["id"], actor="joe", approve=True)
    with pytest.raises(TaskManagerForbidden):
        store.update(item["id"], actor="claude", state="open")
    assert store.item(item["id"])["state"] == "done"
    assert store.update(item["id"], actor="joe", state="open")["state"] == "open"


def test_claude_cannot_write_notes_edit_joes_text_reorder_or_delete(store):
    joes = store.add("all", "joe's", actor="joe")
    with pytest.raises(TaskManagerForbidden):
        store.update(joes["id"], actor="claude", note="mine now")
    with pytest.raises(TaskManagerForbidden):
        store.update(joes["id"], actor="claude", text="rewritten")
    with pytest.raises(TaskManagerForbidden):
        store.add("all", "x", actor="claude", note="a note")
    with pytest.raises(TaskManagerForbidden):
        store.delete(joes["id"], actor="claude")
    with pytest.raises(TaskManagerForbidden):
        store.reorder("all", [joes["id"]], actor="claude", expected_revision=store.list_items("all")["revision"])
    own = store.add("all", "claude's", actor="claude")
    assert store.update(own["id"], actor="claude", text="claude's, edited")["text"] == "claude's, edited"


def test_a_stale_item_revision_is_refused_with_the_stored_item(store):
    item = store.add("all", "x", actor="joe")
    store.update(item["id"], actor="joe", text="y", expected_revision=item["revision"])
    with pytest.raises(TaskManagerStale) as raised:
        store.update(item["id"], actor="joe", text="z", expected_revision=item["revision"])
    assert raised.value.current["text"] == "y"


def test_reorder_sets_priority_and_refuses_a_list_that_moved(store):
    a, b, c = (store.add("all", t, actor="joe")["id"] for t in "abc")
    rev = store.list_items("all")["revision"]
    after = store.reorder("all", [c, a, b], actor="joe", expected_revision=rev)
    assert [i["id"] for i in after["items"]] == [c, a, b]
    store.add("all", "claude just added this", actor="claude")
    with pytest.raises(TaskManagerStale):
        store.reorder("all", [a, b, c], actor="joe", expected_revision=after["revision"])
    with pytest.raises(TaskManagerStale):
        store.reorder("all", [a, b, c], actor="joe", expected_revision=store.list_items("all")["revision"])


def test_joes_reply_answers_claudes_question_and_questions_are_claudes(store):
    item = store.add("all", "need your call: y", actor="claude")
    asked = store.post(item["id"], "which one?", actor="claude", kind="question")
    assert asked["message"]["answered"] is False
    assert store.summary()["lists"]["all"]["questions"] == 1
    with pytest.raises(TaskManagerForbidden):
        store.post(item["id"], "joe asks", actor="joe", kind="question")
    store.post(item["id"], "the second", actor="joe", kind="reply")
    thread = store.item(item["id"])["thread"]
    assert [(m["author"], m["kind"], m["answered"]) for m in thread] == [
        ("claude", "question", True), ("joe", "reply", False)]
    assert store.summary()["lists"]["all"]["questions"] == 0


def test_changes_since_a_cursor_are_only_what_moved(store):
    a = store.add("all", "a", actor="joe")
    store.add("7", "other list", actor="joe")
    cursor = store.changes(0)["cursor"]
    assert store.changes(cursor) == {"cursor": cursor, "reset": False, "items": [], "messages": [], "groups": []}
    store.update(a["id"], actor="joe", approve=True)
    store.post(a["id"], "thanks", actor="claude", kind="reply")
    moved = store.changes(cursor, "all")
    assert [i["id"] for i in moved["items"]] == [a["id"]]
    assert moved["items"][0]["state"] == "done"
    assert [m["text"] for m in moved["messages"] if not m.get("category")] == ["thanks"]
    assert [m["text"] for m in moved["messages"] if m.get("category") == "status"] == ["status changed from open to done by the owner"]
    store.delete(a["id"], actor="joe")
    gone = store.changes(moved["cursor"])
    assert gone["items"][0]["deleted"] is True
    assert store.changes(10_000)["reset"] is True


def test_summary_carries_claudes_newest_post_for_surfacing(store):
    store.add("all", "joe's", actor="joe")
    assert store.summary()["lists"]["all"]["claude_seq"] == 0
    item = store.add("all", "claude's", actor="claude")
    first = store.summary()["lists"]["all"]["claude_seq"]
    assert first == item["created_seq"]
    store.post(item["id"], "q?", actor="claude", kind="question")
    assert store.summary()["lists"]["all"]["claude_seq"] > first


def test_bad_input_is_refused_by_name(store):
    with pytest.raises(TaskManagerInvalid):
        store.add("all", "   ", actor="joe")
    with pytest.raises(TaskManagerInvalid):
        store.add("not-a-list", "x", actor="joe")
    with pytest.raises(TaskManagerInvalid):
        store.add("all", "x" * (rules.MAX_TEXT + 1), actor="joe")
    with pytest.raises(TaskManagerInvalid):
        store.add("all", "x", actor="someone")
    with pytest.raises(TaskManagerNotFound):
        store.update(999, actor="joe", text="x")


def test_the_store_is_at_the_work_ladder_top_and_a_newer_store_is_refused(tmp_path: Path, store):
    store.add("all", "x", actor="joe")
    path = WorkStorage(tmp_path).db_path
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT v FROM work_meta WHERE k = 'work_ladder'").fetchone()[0] == WORK_VERSION
        conn.execute("UPDATE work_meta SET v = ? WHERE k = 'work_ladder'", (WORK_VERSION + 1,))
    ready.forget(path)
    with pytest.raises(CplugSchemaError):
        TaskManagerStore(WorkStorage(tmp_path), notify=lambda t: None).list_items("all")


def test_items_are_numbered_top_down_in_the_current_priority_order(store):
    a, b, c = (store.add("all", t, actor="joe") for t in "abc")
    other = store.add("12", "elsewhere", actor="joe")
    assert [(i["id"], i["number"]) for i in store.list_items("all")["items"]] == [(a["id"], 1), (b["id"], 2), (c["id"], 3)]
    revision = store.list_items("all")["revision"]
    store.reorder("all", [c["id"], a["id"], b["id"]], actor="joe", expected_revision=revision)
    assert [i["number"] for i in store.list_items("all")["items"]] == [1, 2, 3]
    assert store.item(c["id"])["number"] == 1 and store.item(b["id"])["number"] == 3
    assert store.item(other["id"])["number"] == 1
    moved = {i["id"]: i["number"] for i in store.changes(0, "all")["items"]}
    assert moved == {c["id"]: 1, a["id"]: 2, b["id"]: 3}
    store.delete(a["id"], actor="joe")
    gone = {i["id"]: i.get("number") for i in store.changes(0, "all")["items"]}
    assert gone[a["id"]] is None and gone[b["id"]] == 2


def test_kind_is_set_by_either_side_within_the_rules_and_checked(store):
    mine = store.add("all", "need a decision", actor="claude", kind="question")
    joes = store.add("all", "joe item", actor="joe")
    assert mine["kind"] == "question" and joes["kind"] == ""
    assert store.update(mine["id"], actor="claude", kind="done")["kind"] == "done"
    assert store.update(joes["id"], actor="joe", kind="waiting")["kind"] == "waiting"
    assert store.update(mine["id"], actor="joe", kind="")["kind"] == ""
    with pytest.raises(TaskManagerForbidden):
        store.update(joes["id"], actor="claude", kind="info")
    with pytest.raises(TaskManagerInvalid):
        store.update(mine["id"], actor="joe", kind="urgent")
    with pytest.raises(TaskManagerInvalid):
        store.add("all", "x", actor="claude", kind="nope")


def test_a_version_one_file_gains_the_kind_column_and_keeps_its_items(tmp_path: Path):
    path = tmp_path / "huddle.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(MIGRATIONS[0])
        conn.execute("INSERT INTO items (list_key, text, position, created_by, state, created_at, updated_at, created_seq, seq) "
                     "VALUES ('all', 'old row', 0, 'joe', 'open', 1, 1, 1, 1)")
        conn.execute("PRAGMA user_version = 1")
    items = TaskManagerStore(WorkStorage(path.parent), notify=lambda t: None).list_items("all")["items"]
    assert [(i["text"], i["kind"], i["number"], i["unread"]) for i in items] == [("old row", "", 1, False)]
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert conn.execute("SELECT COUNT(*) FROM callers").fetchone()[0] == 0


def test_checked_items_carry_no_number_and_open_ones_count_past_them(store):
    a, b, c = (store.add("all", t, actor="joe") for t in "abc")
    store.update(b["id"], actor="joe", approve=True)
    numbers = {i["id"]: i["number"] for i in store.list_items("all")["items"]}
    assert numbers == {a["id"]: 1, b["id"]: None, c["id"]: 2}
    assert store.item(b["id"])["number"] is None and store.item(c["id"])["number"] == 2
    changed = {i["id"]: i["number"] for i in store.changes(0, "all")["items"]}
    assert changed[b["id"]] is None and changed[c["id"]] == 2
    store.update(b["id"], actor="joe", approve=False)
    assert [i["number"] for i in store.list_items("all")["items"]] == [1, 2, 3]
