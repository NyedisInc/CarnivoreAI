
from __future__ import annotations

import sqlite3
from pathlib import Path

from src.cplugs.huddle import service, structured
from src.cplugs.huddle.store import TaskManagerStore
from src.core.work.ladder import MIGRATIONS, SCHEMA_VERSION
from src.core.work.storage import WorkStorage
from tests.python.cplugs.huddle.test_task_manager_mcp import call, huddle_store, manager  # noqa: F401


def _quiet(monkeypatch):
    monkeypatch.setattr(service, "surface_question", lambda ctx, sid, item, message: True)


def test_a_structured_ask_stores_context_and_numbered_questions_and_flattens_the_text(manager, monkeypatch):
    _quiet(monkeypatch)
    item = huddle_store(manager).add("all", "x", actor="joe")["id"]
    ok, asked = call(manager, "task_manager_ask", {"item": item, "context": "two ways to do the install", "questions": ["a or b?", "tonight?"]})
    assert ok
    assert asked["item"]["thread"][0]["text"] == "two ways to do the install\n\n1. a or b?\n2. tonight?"
    message = huddle_store(manager).item(item)["thread"][0]
    assert message["kind"] == "question" and message["context"] == "two ways to do the install"
    assert message["questions"] == ["a or b?", "tonight?"]
    assert message["text"] == "two ways to do the install\n\n1. a or b?\n2. tonight?"
    assert asked["item"]["status"] == "question"


def test_questions_without_context_and_a_text_only_ask_still_work(manager, monkeypatch):
    _quiet(monkeypatch)
    store = huddle_store(manager)
    a, b = store.add("all", "a", actor="joe")["id"], store.add("all", "b", actor="joe")["id"]
    ok, only = call(manager, "task_manager_ask", {"item": a, "questions": ["one?"]})
    first = store.item(a)["thread"][0]
    assert ok and first["context"] == "" and first["text"] == "1. one?" and first["questions"] == ["one?"]
    ok, plain = call(manager, "task_manager_ask", {"item": b, "text": "what did you mean?"})
    msg = store.item(b)["thread"][0]
    assert ok and (msg["text"], msg["context"], msg["questions"]) == ("what did you mean?", "", [])


def test_refusals(manager, monkeypatch):
    _quiet(monkeypatch)
    item = huddle_store(manager).add("all", "x", actor="joe")["id"]
    for bad in ({}, {"context": "only background"}, {"questions": []}, {"questions": ["ok", ""]}, {"questions": ["q"] * (structured.MAX_QUESTIONS + 1)},
                {"questions": ["x" * (structured.MAX_QUESTION + 1)]}):
        ok, text = call(manager, "task_manager_ask", {"item": item, **bad})
        assert not ok, bad
    assert huddle_store(manager).item(item)["thread"] == []


def test_a_reply_cannot_smuggle_parts(manager):
    item = huddle_store(manager).add("all", "x", actor="joe")["id"]
    ok, replied = call(manager, "task_manager_reply", {"item": item, "text": "fyi", "parts": '{"context":"c","questions":["q"]}'})
    msg = huddle_store(manager).item(item)["thread"][0]
    assert msg["questions"] == [] and msg["context"] == ""


def test_the_batch_ask_op_takes_the_structured_fields(manager, monkeypatch):
    _quiet(monkeypatch)
    store = huddle_store(manager)
    a, b = store.add("12", "a", actor="joe")["id"], store.add("12", "b", actor="joe")["id"]
    ops = [{"op": "ask", "item_id": a, "context": "background", "questions": ["q1?", "q2?"]}, {"op": "ask", "item_id": b, "text": "plain?"},
           {"op": "ask", "item_id": b, "context": "no questions"}]
    ok, body = call(manager, "task_manager_batch_run", {"list_id": "12", "ops": ops})
    assert ok and [r["ok"] for r in body["results"]] == [True, True, False]
    assert store.item(a)["thread"][0]["questions"] == ["q1?", "q2?"] and store.item(a)["thread"][0]["context"] == "background"
    assert store.item(b)["thread"][0]["questions"] == [] and store.item(b)["thread"][0]["text"] == "plain?"


def test_owners_numbered_answer_is_a_plain_reply_that_answers_the_question(manager, monkeypatch):
    _quiet(monkeypatch)
    store = huddle_store(manager)
    item = store.add("all", "x", actor="joe")["id"]
    call(manager, "task_manager_ask", {"item": item, "questions": ["a?", "b?"]})
    done = store.post(item, "1 yes, 2 no", actor="joe")["item"]
    assert done["status"] != "question" and done["thread"][0]["answered"] is True


def test_a_rung_16_file_upgrades_and_old_questions_render_as_plain_text(tmp_path: Path):
    path = tmp_path / "huddle.db"
    with sqlite3.connect(path) as conn:
        for step in MIGRATIONS[:16]:
            conn.executescript(step)
        conn.execute("INSERT INTO items (list_key, text, position, created_by, state, created_at, updated_at, created_seq, seq) "
                     "VALUES ('all', 'row', 0, 'joe', 'open', 1, 1, 1, 2)")
        conn.execute("INSERT INTO messages (item_id, author, kind, text, created_at, seq) VALUES (1, 'claude', 'question', 'old question?', 1, 2)")
        conn.execute("PRAGMA user_version = 16")
    item = TaskManagerStore(WorkStorage(path.parent), notify=lambda t: None).list_items("all")["items"][0]
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    msg = item["thread"][0]
    assert (msg["text"], msg["context"], msg["questions"], msg["answered"]) == ("old question?", "", [], False)


def test_a_damaged_parts_value_reads_as_a_plain_question():
    row = {"parts": "{not json"}

    class R(dict):
        def keys(self):
            return super().keys()

    assert structured.wire(R(row)) == ("", [])
