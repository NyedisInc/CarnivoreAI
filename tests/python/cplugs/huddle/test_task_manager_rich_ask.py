
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.huddle import answers, rich_ask, service, structured
from src.cplugs.huddle.rules import TaskManagerInvalid
from tests.python.cplugs.huddle.test_task_manager_mcp import call, huddle_store, manager  # noqa: F401

FORM = [
    {"id": "i54", "type": "yes_no", "prompt": "Close #54?", "labels": ["close", "keep"], "recommend": {"value": True, "reason": "#1164 has it"}},
    {"id": "i728", "type": "single", "prompt": "What about #728?", "other": True, "options": [
        {"id": "fold", "label": "fold it", "recommended": True, "reason": "one renderer"}, {"id": "link", "label": "cross-link"}]},
    {"id": "tags", "type": "multi", "prompt": "Which?", "min": 1, "options": [{"label": "a"}, {"label": "b"}, {"label": "c"}]},
    {"id": "ord", "type": "rank", "prompt": "Order them", "options": [{"id": "x", "label": "X"}, {"id": "y", "label": "Y"}],
     "recommend": {"order": ["y", "x"], "reason": "y is cheaper"}},
    {"id": "why", "type": "short_text", "prompt": "Why?", "required": False},
    "Anything else?",
]


def _quiet(monkeypatch):
    monkeypatch.setattr(service, "surface_question", lambda ctx, sid, item, message: True)


def _ask(manager, monkeypatch, questions=FORM, context="seven rulings"):
    _quiet(monkeypatch)
    store = huddle_store(manager)
    item = store.add("all", "x", actor="joe")["id"]
    ok, asked = call(manager, "task_manager_ask", {"item": item, "context": context, "questions": questions})
    assert ok, asked
    return store, item, asked


def test_a_typed_ask_is_normalized_stored_as_v2_and_answers_its_ids(manager, monkeypatch):
    store, item, asked = _ask(manager, monkeypatch)
    assert asked["question_ids"] == ["i54", "i728", "tags", "ord", "why", "q6"]
    message = store.item(item)["thread"][0]
    assert [q["id"] for q in message["form"]] == asked["question_ids"]
    assert message["form"][2]["options"][1] == {"id": "o2", "label": "b"}
    assert message["form"][5] == {"id": "q6", "type": "long_text", "prompt": "Anything else?", "required": False}
    assert message["questions"][0] == "Close #54?" and message["context"] == "seven rulings"
    assert message["text"].startswith("seven rulings\n\n1. Close #54? (close / keep; recommended: close)")
    assert "   a. fold it (recommended: one renderer)" in message["text"] and "   (or other)" in message["text"]
    assert "2. What happens" not in message["text"]


def test_all_string_asks_stay_the_plain_form_and_a_reply_still_answers_them(manager, monkeypatch):
    store, item, _ = _ask(manager, monkeypatch, ["a?", "b?"])
    message = store.item(item)["thread"][0]
    assert "form" not in message and message["questions"] == ["a?", "b?"]
    store.post(item, "1 yes", actor="joe", kind="reply")
    assert store.item(item)["thread"][0]["answered"] is True


@pytest.mark.parametrize("bad", [
    {"type": "nope", "prompt": "x"}, {"id": "A!", "type": "yes_no", "prompt": "x"},
    {"type": "single", "prompt": "x", "options": [{"label": "only"}]},
    {"type": "yes_no", "prompt": "x", "options": [{"label": "a"}, {"label": "b"}]},
    {"type": "rank", "prompt": "x", "options": [{"id": "a", "label": "a"}, {"id": "b", "label": "b"}], "recommend": {"order": ["a"]}},
    {"type": "rank", "prompt": "x", "options": [{"label": "a", "recommended": True}, {"label": "b"}]},
    {"type": "multi", "prompt": "x", "min": 3, "max": 1, "options": [{"label": "a"}, {"label": "b"}, {"label": "c"}]},
    {"type": "single", "prompt": "x", "recommend": {"value": 1}, "options": [{"label": "a"}, {"label": "b"}]},
    {"type": "single", "prompt": "x", "options": [{"label": "a", "recommended": True}, {"label": "b", "recommended": True}]},
    {"type": "yes_no", "prompt": "x", "recommend": {"value": "yes"}}, {"type": "long_text"},
])
def test_a_bad_typed_question_is_refused_naming_it(manager, monkeypatch, bad):
    _quiet(monkeypatch)
    item = huddle_store(manager).add("all", "x", actor="joe")["id"]
    ok, text = call(manager, "task_manager_ask", {"item": item, "questions": [bad]})
    assert not ok and "question" in text
    assert huddle_store(manager).item(item)["thread"] == []


def test_duplicate_ids_are_refused():
    with pytest.raises(TaskManagerInvalid, match="duplicate id"):
        rich_ask.normalize([{"id": "a", "type": "yes_no", "prompt": "x"}, {"id": "a", "type": "yes_no", "prompt": "y"}])


def test_the_batch_ask_op_takes_typed_questions(manager, monkeypatch):
    _quiet(monkeypatch)
    item = huddle_store(manager).add("all", "x", actor="joe")["id"]
    ok, result = call(manager, "task_manager_batch_run", {"list_id": "all", "ops": [
        {"op": "ask", "item_id": item, "questions": [{"id": "go", "type": "yes_no", "prompt": "go?"}]}]})
    assert ok and result["applied"] == 1
    assert huddle_store(manager).item(item)["thread"][0]["form"][0]["id"] == "go"


ANSWERS = {"i54": {"value": True}, "i728": {"choice": "fold"}, "tags": {"choices": ["o1", "o3"], "note": "not b"},
           "ord": {"order": ["x", "y"]}}


def test_validate_fills_prompts_labels_and_whether_the_recommendation_was_taken():
    form, _ = rich_ask.normalize(FORM)
    out = answers.validate(form, ANSWERS)
    assert out["i54"] == {"value": True, "label": "close", "recommended": True, "prompt": "Close #54?"}
    assert out["i728"]["label"] == "fold it" and out["i728"]["recommended"] is True
    assert out["tags"]["labels"] == ["a", "c"] and out["tags"]["note"] == "not b" and "recommended" not in out["tags"]
    assert out["ord"] == {"order": ["x", "y"], "labels": ["X", "Y"], "recommended": False, "prompt": "Order them"}
    assert out["why"] == {"skipped": True, "prompt": "Why?"}
    text = answers.text_of(form, out)
    assert text.startswith("answers to 6 questions:\n1. Close #54? close (recommended)")
    assert "4. Order them X > Y (not the recommendation)" in text and "3. Which? a, c; note: not b" in text and "5. Why? skipped" in text


@pytest.mark.parametrize("given,why", [
    ({}, "required questions left unanswered: i54, i728, tags, ord"),
    ({**ANSWERS, "ghost": {"value": 1}}, "no such question: ghost"),
    ({**ANSWERS, "i728": {"choice": "nope"}}, "choice must be a known option id"),
    ({**ANSWERS, "tags": {"choices": []}}, "required questions left unanswered: tags"),
    ({**ANSWERS, "ord": {"order": ["x"]}}, "order must rank every option"),
    ({**ANSWERS, "i54": {"value": "yes"}}, "value must be true or false"),
    ({**ANSWERS, "i728": {"choice": None, "other": "hm"}, "why": {"text": "x" * 501}}, "over 500"),
])
def test_validate_refuses_with_the_question_named(given, why):
    form, _ = rich_ask.normalize(FORM)
    with pytest.raises(TaskManagerInvalid, match=why):
        answers.validate(form, given)


def test_a_single_other_answer_is_kept_and_a_text_recommendation_compares():
    form, _ = rich_ask.normalize([{"id": "a", "type": "single", "prompt": "p", "other": True, "options": [{"label": "x"}, {"label": "y"}]},
                                  {"id": "t", "type": "short_text", "prompt": "t", "recommend": {"text": "same"}}])
    out = answers.validate(form, {"a": {"choice": None, "other": "z"}, "t": {"text": "same"}})
    assert out["a"] == {"choice": None, "other": "z", "prompt": "p"} and out["t"]["recommended"] is True
    assert "a: " not in answers.text_of(form, out) and "other: z" in answers.text_of(form, out)


@pytest.fixture
def client(manager):
    manager.app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    from src.cplugs.huddle import routes
    manager.app.include_router(routes.router, prefix="/api/v1")
    with TestClient(manager.app) as test_client:
        yield test_client


def test_routes_need_auth(manager):
    from src.cplugs.huddle import routes
    manager.app.include_router(routes.router, prefix="/api/v1")
    with TestClient(manager.app) as anonymous:
        assert anonymous.get("/api/v1/cplugs/huddle/questions/1").status_code in (401, 403)
        assert anonymous.post("/api/v1/cplugs/huddle/questions/1/answer", json={"answers": {}}).status_code in (401, 403)


def test_submit_posts_one_keyed_answer_answers_only_that_question_and_claude_reads_it(manager, monkeypatch, client):
    store, item, asked = _ask(manager, monkeypatch)
    qid = asked["item"]["thread"][0]["id"]
    got = client.get(f"/api/v1/cplugs/huddle/questions/{qid}").json()
    assert got["typed"] and got["answered"] is False and [q["id"] for q in got["ask"]["questions"]][:2] == ["i54", "i728"]
    bad = client.post(f"/api/v1/cplugs/huddle/questions/{qid}/answer", json={"answers": {}})
    assert bad.status_code == 400 and bad.json()["detail"]["code"] == "task_manager_invalid"
    done = client.post(f"/api/v1/cplugs/huddle/questions/{qid}/answer", json={"answers": ANSWERS})
    assert done.status_code == 200, done.text
    thread = store.item(item)["thread"]
    assert thread[0]["answered"] is True and thread[1]["author"] == "joe" and thread[1]["answers_to"] == qid
    assert thread[1]["answers"]["i54"]["recommended"] is True and thread[1]["text"].startswith("answers to 6 questions:")
    assert store.item(item)["status"] != "question"
    again = client.post(f"/api/v1/cplugs/huddle/questions/{qid}/answer", json={"answers": ANSWERS})
    assert again.status_code == 200 and again.json()["replayed"] is True and again.json()["message"]["id"] == thread[1]["id"]
    assert len(store.item(item)["thread"]) == len(thread)
    other = client.post(f"/api/v1/cplugs/huddle/questions/{qid}/answer", json={"answers": {**ANSWERS, "i54": {"value": False}}})
    assert other.status_code == 409 and other.json()["detail"]["code"] == "task_manager_answered"
    assert client.get(f"/api/v1/cplugs/huddle/questions/{qid}").json()["answer_message_id"] == thread[1]["id"]
    assert client.get("/api/v1/cplugs/huddle/questions/99999").status_code == 404
    ok, changes = call(manager, "task_manager_changes", {"since": 0, "include_mine": True})
    sent = [m for m in changes["messages"] if m.get("answers_to")]
    assert sent and sent[0]["answers"]["ord"]["order"] == ["x", "y"] and sent[0]["answers_to"] == qid
    ask_wire = next(m for m in changes["messages"] if m["id"] == qid)
    assert [q["id"] for q in ask_wire["form"]][0] == "i54"
    assert "answers_to" in next(m for m in call(manager, "task_manager_tasks_list", {"list": "all", "fields": ["thread"]})[1]["items"][0]["thread"] if m["id"] == sent[0]["id"])


def test_a_reply_on_a_typed_ask_answers_it_provisionally_and_the_tell_number_counts_it(manager, monkeypatch):
    store, item, _ = _ask(manager, monkeypatch)
    store.post(item, "wait, what about #1071?", actor="joe", kind="reply")
    row = store.item(item)
    assert row["thread"][0]["answered"] is True and row["status"] != "question"
    assert store.summary()["lists"]["all"]["waiting_to_send"] == 1


def test_the_wire_shape_of_a_plain_question_is_unchanged(manager, monkeypatch):
    _quiet(monkeypatch)
    store = huddle_store(manager)
    item = store.add("all", "x", actor="joe")["id"]
    call(manager, "task_manager_ask", {"item": item, "text": "what?"})
    message = store.item(item)["thread"][0]
    assert not {"form", "answers", "answers_to"} & set(message)
    assert structured.question_ids("") == [] and json.loads(rich_ask.dump("c", []))["v"] == 2


def test_a_single_command_is_normalized_flattened_and_refused_on_other_types():
    opts = [{"id": "ran", "label": "ran it"}, {"id": "fail", "label": "failed"}]
    form, typed = rich_ask.normalize([{"id": "ho", "type": "single", "prompt": "Run it", "options": opts, "command": "ls -la"}])
    assert typed and form[0]["command"] == {"text": "ls -la"}
    form, _ = rich_ask.normalize([{"id": "ho", "type": "single", "prompt": "Run it", "options": opts, "command": {"text": " x\ny ", "lang": "bash"}}])
    assert form[0]["command"] == {"text": "x\ny", "lang": "bash"}
    assert "   ```bash" in rich_ask.flatten("", form) and "   x" in rich_ask.flatten("", form)
    for bad in ({"text": ""}, {"text": "x", "lang": "two words"}, {"text": "x" * (rich_ask.MAX_COMMAND + 1)}, 5, {"lang": "bash"}):
        with pytest.raises(TaskManagerInvalid):
            rich_ask.normalize([{"type": "single", "prompt": "p", "options": opts, "command": bad}])
    with pytest.raises(TaskManagerInvalid, match="takes no command"):
        rich_ask.normalize([{"type": "multi", "prompt": "p", "options": opts, "command": "ls"}])
    with pytest.raises(TaskManagerInvalid, match="takes no command"):
        rich_ask.normalize([{"type": "yes_no", "prompt": "p", "command": "ls"}])


def test_the_command_survives_storage_and_the_answer_shape_is_unchanged():
    opts = [{"id": "ran", "label": "ran it"}, {"id": "fail", "label": "failed"}]
    form, _ = rich_ask.normalize([{"id": "ho", "type": "single", "prompt": "Run it", "options": opts, "command": {"text": "ls", "lang": "sh"}}])
    stored = rich_ask.form_of(rich_ask.dump("ctx", form))
    assert stored[0]["command"] == {"text": "ls", "lang": "sh"}


def test_dismiss_skips_required_questions_and_reads_dismissed() -> None:
    questions = [{"id": "a", "type": "yes_no", "prompt": "ok?", "required": True}, {"id": "b", "type": "single", "prompt": "which?", "required": True, "options": [{"id": "x", "label": "X"}]}]
    out = answers.validate(questions, {q["id"]: {"skipped": True, "dismissed": True} for q in questions})
    assert out["a"] == {"skipped": True, "dismissed": True, "prompt": "ok?"}
    assert "1. ok? dismissed" in answers.text_of(questions, out)
    assert answers.lines_of(out)[1] == "2. which?: dismissed"
    with pytest.raises(TaskManagerInvalid):
        answers.validate(questions, {})


def test_a_command_question_must_stand_alone_in_its_form():
    opts = [{"id": "ran", "label": "ran it"}, {"id": "fail", "label": "failed"}]
    handoff = {"id": "ho", "type": "single", "prompt": "Run it", "options": opts, "command": "ls -la"}
    other = {"id": "why", "type": "long_text", "prompt": "anything else?"}
    with pytest.raises(TaskManagerInvalid, match="separate task_manager_ask"):
        rich_ask.normalize([handoff, other])
    with pytest.raises(TaskManagerInvalid, match="ONLY question"):
        rich_ask.normalize(["a plain question?", handoff])
    form, _ = rich_ask.normalize([handoff])
    assert [q["id"] for q in form] == ["ho"]
    assert len(rich_ask.normalize([other, {"id": "n", "type": "yes_no", "prompt": "ok?"}])[0]) == 2


def test_the_anything_else_box_carries_pasted_files_into_the_answer_text():
    form = [{"id": "q1", "type": "yes_no", "prompt": "ok?", "required": True}]
    checked = answers.validate(form, {"q1": {"value": True}, "_extra": {"text": "see this", "files": ["/abs/shot.png"]}})
    assert checked["_extra"] == {"text": "see this", "files": ["/abs/shot.png"]}
    assert answers.text_of(form, checked).endswith("anything else: see this; file: /abs/shot.png")
    only_file = answers.validate(form, {"q1": {"value": True}, "_extra": {"files": ["/abs/shot.png"]}})
    assert only_file["_extra"]["files"] == ["/abs/shot.png"]
    with pytest.raises(TaskManagerInvalid):
        answers.validate(form, {"q1": {"value": True}, "_extra": {"text": "x", "files": ["relative.png"]}})
