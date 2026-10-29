
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.huddle import answers, kinds, rich_ask, service
from src.cplugs.huddle.rules import TaskManagerForbidden, TaskManagerInvalid
from tests.python.cplugs.huddle.test_task_manager_mcp import call, huddle_store, manager  # noqa: F401

FORM = [{"id": "go", "type": "yes_no", "prompt": "Ship it?"}, {"id": "why", "type": "short_text", "prompt": "Why?", "required": False}]


@pytest.fixture
def client(manager):
    manager.app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    from src.cplugs.huddle import routes
    manager.app.include_router(routes.router, prefix="/api/v1")
    with TestClient(manager.app) as test_client:
        yield test_client


def _item(manager):
    store = huddle_store(manager)
    return store, store.add("all", "work", actor="joe")["id"]


def test_an_answer_post_quotes_joes_message_as_a_snapshot_and_behaves_like_an_info(manager):
    store, item = _item(manager)
    asked = store.post(item, "can we ship friday?", actor="joe")["message"]["id"]
    ok, out = call(manager, "task_manager_reply", {"item": item, "text": "yes, friday works", "kind": "answer", "quote": asked})
    assert ok, out
    assert out["kind"] == "answer"
    row = store.item(item)
    message = row["thread"][-1]
    assert message["quote"] == {"id": asked, "text": "can we ship friday?"}
    assert message["unread"] is True and row["info_unread"] == 1 and row["info_unseen"] is True
    assert row["unread"] is False and row["attention_unread"] == 0
    assert row["status"] != "question" and row["status"] != "info"
    assert message["quote"]["text"] == "can we ship friday?"
    other = store.post(item, "second", actor="joe")["message"]["id"]
    assert other != asked and store.item(item)["thread"][-2]["quote"]["text"] == "can we ship friday?"


def test_an_answer_read_one_by_one_clears_the_info_count(manager):
    store, item = _item(manager)
    call(manager, "task_manager_reply", {"item": item, "text": "a", "kind": "answer", "quote_text": "asked in the terminal"})
    row = store.item(item)
    answer = row["thread"][-1]
    assert answer["quote"] == {"id": None, "text": "asked in the terminal"}
    store.mark_seen(item, answer["id"])
    assert store.item(item)["info_unread"] == 0


@pytest.mark.parametrize("args, why", [
    ({"kind": "answer"}, "quotes the question"),
    ({"kind": "answer", "quote": 1, "quote_text": "both"}, "quotes the question"),
    ({"kind": "info", "quote": 1}, "only on an answer"),
    ({"kind": "answer", "quote": 99999}, "not on item"),
])
def test_an_answer_needs_exactly_one_real_quote(manager, args, why):
    store, item = _item(manager)
    store.post(item, "q", actor="joe")
    ok, out = call(manager, "task_manager_reply", {"item": item, "text": "a", **args})
    assert not ok and why in str(out)


def test_an_answer_cannot_quote_another_items_message_and_joe_cannot_post_one(manager):
    store, item = _item(manager)
    other = store.add("all", "elsewhere", actor="joe")["id"]
    foreign = store.post(other, "not here", actor="joe")["message"]["id"]
    ok, out = call(manager, "task_manager_reply", {"item": item, "text": "a", "kind": "answer", "quote": foreign})
    assert not ok and "not on item" in str(out)
    with pytest.raises(TaskManagerForbidden):
        store.post(item, "x", actor="joe", kind=kinds.ANSWER, quote_text="q")


def test_the_quote_is_cut_at_the_limit(manager):
    store, item = _item(manager)
    posted = store.post(item, "x" * 900 + "tail" * 100, actor="joe")["message"]["id"]
    call(manager, "task_manager_reply", {"item": item, "text": "a", "kind": "answer", "quote": posted})
    assert len(store.item(item)["thread"][-1]["quote"]["text"]) == 1000


def test_extra_validates_rides_the_answer_and_lands_in_the_text_fallback():
    form, _ = rich_ask.normalize(FORM)
    out = answers.validate(form, {"go": {"value": True}, "_extra": {"text": "  also check the docs  "}})
    assert out["_extra"] == {"text": "also check the docs"}
    text = answers.text_of(form, out)
    assert text.endswith("anything else: also check the docs") and text.startswith("answers to 2 questions:")
    assert "_extra" not in answers.validate(form, {"go": {"value": True}, "_extra": {"text": "  "}})
    for bad in ({"text": 5}, "text", {"text": "x" * 4001}):
        with pytest.raises(TaskManagerInvalid, match="_extra"):
            answers.validate(form, {"go": {"value": True}, "_extra": bad})


def test_submit_with_extra_is_born_read_and_claude_reads_it_through_changes(manager, monkeypatch, client):
    monkeypatch.setattr(service, "surface_question", lambda ctx, sid, item, message: True)
    store, item = _item(manager)
    ok, asked = call(manager, "task_manager_ask", {"item": item, "context": "ctx", "questions": FORM})
    assert ok, asked
    qid = asked["item"]["thread"][0]["id"]
    done = client.post(f"/api/v1/cplugs/huddle/questions/{qid}/answer", json={"answers": {"go": {"value": False}, "_extra": {"text": "but wait for the release"}}})
    assert done.status_code == 200, done.text
    row = store.item(item)
    given = row["thread"][1]
    assert given["answers"]["_extra"] == {"text": "but wait for the release"} and "anything else: but wait for the release" in given["text"]
    assert given["unread"] is False and row["unread"] is False and row["info_unread"] == 0 and row["attention_unread"] == 0
    seen = store._connect(False).execute("SELECT seen FROM work_messages WHERE id = ?", (given["id"],)).fetchone()[0]
    assert seen == 1
    ok, changes = call(manager, "task_manager_changes", {"since": 0})
    sent = [m for m in changes["messages"] if m.get("answers_to")]
    assert sent[0]["answers"]["_extra"] == {"text": "but wait for the release"}


ENTRY = {"id": "ab12cd34", "name": "shot.png", "mime": "image/png", "size": 9, "path": "files/1/ab12cd34.png"}


def _stored(store) -> None:
    target = store._storage.path / ENTRY["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"x" * ENTRY["size"])


def test_an_answer_with_files_keeps_the_quote_and_the_files_in_parts_and_on_the_wire(manager):
    import json

    from src.cplugs.huddle import files
    store, item = _item(manager)
    asked = store.post(item, "show me the screen", actor="joe")["message"]["id"]
    _stored(store)
    store.post(item, "here", actor="claude", kind="answer", quote=asked, parts=files.parts_of([ENTRY]))
    message = store.item(item)["thread"][-1]
    assert message["quote"] == {"id": asked, "text": "show me the screen"}
    assert [f["id"] for f in message["files"]] == ["ab12cd34"]
    with store._connect(False) as conn:
        stored = json.loads(conn.execute("SELECT parts FROM work_messages WHERE id = ?", (message["id"],)).fetchone()[0])
    assert set(stored) == {"quote", "files"}
    with store._connect(False) as conn:
        assert conn.execute(f"SELECT COUNT(*) FROM work_messages WHERE id = ? AND {files.PARTS_SQL}", (message["id"],)).fetchone()[0] == 1


def test_an_answer_with_a_quote_and_files_and_an_offer_keeps_all_three(manager):
    from datetime import datetime, timedelta, timezone

    from src.cplugs.huddle import files
    store, item = _item(manager)
    when = (datetime.now(timezone.utc) + timedelta(days=3)).replace(microsecond=0).isoformat()
    _stored(store)
    store.post(item, "ok", actor="claude", kind="answer", quote_text="asked outside", parts=files.parts_of([ENTRY]),
               offer={"when": when, "title": "check back", "state": "offered"})
    message = store.item(item)["thread"][-1]
    assert message["quote"]["text"] == "asked outside" and message["files"][0]["id"] == "ab12cd34"
    assert message["schedule"]["title"] == "check back"


def test_an_offer_on_a_reply_with_files_keeps_the_files(manager):
    from datetime import datetime, timedelta, timezone

    from src.cplugs.huddle import files
    store, item = _item(manager)
    when = (datetime.now(timezone.utc) + timedelta(days=3)).replace(microsecond=0).isoformat()
    _stored(store)
    store.post(item, "see attached", actor="claude", parts=files.parts_of([ENTRY]), offer={"when": when, "title": "t", "state": "offered"})
    message = store.item(item)["thread"][-1]
    assert message["files"][0]["id"] == "ab12cd34" and message["schedule"]["title"] == "t"
