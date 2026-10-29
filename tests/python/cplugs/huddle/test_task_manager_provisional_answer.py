
from __future__ import annotations

from contextlib import closing

from src.cplugs.huddle import service, sends
from tests.python.cplugs.huddle.test_task_manager_mcp import call, huddle_store, manager  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_rich_ask import ANSWERS, FORM, _ask, client  # noqa: F401


def _plain_ask(manager, monkeypatch, item=None):
    monkeypatch.setattr(service, "surface_question", lambda ctx, sid, item, message: True)
    store = huddle_store(manager)
    item = item or store.add("all", "x", actor="joe")["id"]
    ok, out = call(manager, "task_manager_ask", {"item": item, "text": "what?"})
    assert ok, out
    return store, item


def test_owner_reply_answers_the_open_typed_question_and_tells_the_agent(manager, monkeypatch):
    store, item, _ = _ask(manager, monkeypatch)
    qid = store.item(item)["thread"][0]["id"]
    posted = store.post(item, "do 1 but skip the rest", actor="joe", kind="reply")["message"]
    row = store.item(item)
    assert row["thread"][0]["answered"] is True
    assert row["status"] != "question"
    assert posted["answers_to"] == qid and posted["freeform"] is True and "answers" not in posted
    assert posted["text"] == "do 1 but skip the rest"
    assert store.summary()["lists"]["all"]["waiting_to_send"] == 1
    ok, changes = call(manager, "task_manager_changes", {"since": 0, "include_mine": True})
    sent = [m for m in changes["messages"] if m.get("freeform")]
    assert sent and sent[0]["answers_to"] == qid and sent[0]["text"] == "do 1 but skip the rest"


def test_no_open_question_changes_nothing(manager, monkeypatch):
    monkeypatch.setattr(service, "surface_question", lambda ctx, sid, item, message: True)
    store = huddle_store(manager)
    item = store.add("all", "x", actor="joe")["id"]
    message = store.post(item, "just a note", actor="joe", kind="reply")["message"]
    assert "freeform" not in message and "answers_to" not in message


def test_an_already_answered_question_is_not_answered_again(manager, monkeypatch):
    store, item, _ = _ask(manager, monkeypatch)
    store.post(item, "first", actor="joe", kind="reply")
    second = store.post(item, "second", actor="joe", kind="reply")["message"]
    assert "freeform" not in second


def test_an_agent_reply_never_answers(manager, monkeypatch):
    store, item, _ = _ask(manager, monkeypatch)
    store.post(item, "an info", actor="claude", kind="info")
    assert store.item(item)["thread"][0]["answered"] is False


def test_only_the_newest_open_question_is_open_and_the_older_one_is_superseded(manager, monkeypatch):
    store, item, _ = _ask(manager, monkeypatch)
    ok, out = call(manager, "task_manager_ask", {"item": item, "questions": [{"id": "z", "type": "yes_no", "prompt": "again?"}]})
    assert ok, out
    store.post(item, "comment", actor="joe", kind="reply")
    asks = [m for m in store.item(item)["thread"] if m["kind"] == "question"]
    assert [m["answered"] for m in asks] == [True, True]
    assert [m.get("superseded", False) for m in asks] == [True, False]


def test_a_plain_ask_is_still_answered_by_a_reply_without_the_marker(manager, monkeypatch):
    store, item = _plain_ask(manager, monkeypatch)
    message = store.post(item, "yes", actor="joe", kind="reply")["message"]
    assert store.item(item)["thread"][0]["answered"] is True and "freeform" not in message


def test_a_new_question_after_the_comment_works_and_its_typed_answer_still_submits(manager, monkeypatch, client):
    store, item, _ = _ask(manager, monkeypatch)
    store.post(item, "actually, think about X", actor="joe", kind="reply")
    ok, out = call(manager, "task_manager_ask", {"item": item, "context": "new", "questions": FORM})
    assert ok, out
    assert store.item(item)["status"] == "question"
    qid = [m for m in store.item(item)["thread"] if m["kind"] == "question"][-1]["id"]
    done = client.post(f"/api/v1/cplugs/huddle/questions/{qid}/answer", json={"answers": ANSWERS})
    assert done.status_code == 200, done.text
    assert store.item(item)["status"] != "question"


def _claim(store, item):
    with closing(store._connect(False)) as conn:
        row = conn.execute("SELECT claude_working, claude_working_by FROM work_items WHERE id = ?", (item,)).fetchone()
        asker = conn.execute("SELECT author_key FROM work_messages WHERE item_id = ? AND kind = 'question' ORDER BY id LIMIT 1", (item,)).fetchone()
    return row[0], row[1], asker[0] if asker else ""


def test_the_provisional_answer_moves_the_item_to_working_for_the_asker(manager, monkeypatch):
    store, item, _ = _ask(manager, monkeypatch)
    store.post(item, "yellow", actor="joe", kind="reply")
    working, holder, asker = _claim(store, item)
    assert asker and working == 1 and holder == asker
    with closing(store._connect(True)) as conn, conn:
        sends.record_send(conn, ["all"], 10**9)
    assert store.item(item)["status"] == "working"


def test_a_reply_that_reopens_a_review_item_still_ends_in_working(manager, monkeypatch):
    store, item, _ = _ask(manager, monkeypatch)
    store.update(item, actor="joe", state="review")
    store.post(item, "yellow", actor="joe", kind="reply")
    assert _claim(store, item)[0] == 1


def test_a_reply_with_no_open_typed_question_claims_nothing(manager, monkeypatch):
    monkeypatch.setattr(service, "surface_question", lambda ctx, sid, item, message: True)
    store = huddle_store(manager)
    item = store.add("all", "x", actor="joe")["id"]
    store.post(item, "just a note", actor="joe", kind="reply")
    assert _claim(store, item)[:2] == (0, "")
