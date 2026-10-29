
from __future__ import annotations

from contextlib import closing
from pathlib import Path

import pytest

from src.cplugs.huddle import answers, lineage, owner_guards
from src.cplugs.huddle.cards import state_log
from tests.python.cplugs.huddle.test_task_manager_mcp import call, huddle_store, manager  # noqa: F401

HANDOFF = "20261015-cleanup"


@pytest.fixture(autouse=True)
def handoff_root(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "handoff-root"
    (root / "log").mkdir(parents=True)
    (root / "pending").mkdir()
    queue(root, HANDOFF)
    monkeypatch.setattr(owner_guards, "HANDOFF_ROOT", root)
    return root


def queue(root: Path, name: str) -> None:
    (root / "pending" / f"{name}.sh").write_text("#!/bin/bash\n")


def _item(manager, text: str = "work") -> tuple:
    store = huddle_store(manager)
    return store, store.add("12", text, actor="joe")["id"]


def _reply(manager, item: int, **args) -> dict:
    ok, out = call(manager, "task_manager_reply", {"item": item, **args}, raw=True)
    assert ok, out
    return out


def _review(manager, item: int, **extra) -> tuple:
    return call(manager, "task_manager_update", {"item": item, "state": "review", **extra})




@pytest.mark.parametrize("kind", [None, "info", "attention"])
def test_an_info_after_an_unanswered_owner_question_is_stored_as_an_answer_quoting_it(manager, kind):
    store, item = _item(manager)
    asked = store.post(item, "can we ship friday?", actor="joe")["message"]["id"]
    out = _reply(manager, item, text="yes, friday works", **({"kind": kind} if kind else {}))
    assert out[owner_guards.STORED_AS_ANSWER_TO] == asked
    assert f"answer to the owner's message {asked}" in out[owner_guards.GUARD_NOTE]
    message = store.item(item)["thread"][-1]
    assert message["kind"] == "answer" and message["quote"] == {"id": asked, "text": "can we ship friday?"}
    assert store.item(item)["unread"] is False


def test_not_a_question_does_not_bypass_the_answer_guard(manager):
    store, item = _item(manager)
    asked = store.post(item, "status?", actor="joe")["message"]["id"]
    out = _reply(manager, item, text="all green", not_a_question=True)
    assert out[owner_guards.STORED_AS_ANSWER_TO] == asked and store.item(item)["thread"][-1]["kind"] == "answer"


def test_an_info_after_an_owner_form_submit_stays_info(manager):
    store, item = _item(manager)
    store.post(item, "ship? yes", actor="joe", parts=answers.dump(5, {"go": {"value": True}}))
    out = _reply(manager, item, text="shipping now")
    assert owner_guards.STORED_AS_ANSWER_TO not in out and store.item(item)["thread"][-1]["kind"] == "info"


def test_a_form_submit_stops_the_look_back_at_older_owner_messages(manager):
    store, item = _item(manager)
    store.post(item, "an older question?", actor="joe")
    store.post(item, "ship? yes", actor="joe", parts=answers.dump(5, {"go": {"value": True}}))
    assert _reply(manager, item, text="shipping now").get(owner_guards.STORED_AS_ANSWER_TO) is None


def test_an_info_with_no_owner_message_stays_info(manager):
    store, item = _item(manager)
    out = _reply(manager, item, text="started")
    assert owner_guards.STORED_AS_ANSWER_TO not in out and store.item(item)["thread"][-1]["kind"] == "info"


def test_after_an_answer_the_next_info_stays_info(manager):
    store, item = _item(manager)
    asked = store.post(item, "why?", actor="joe")["message"]["id"]
    _reply(manager, item, text="because", kind="answer", quote=asked)
    out = _reply(manager, item, text="also fixed the test")
    assert owner_guards.STORED_AS_ANSWER_TO not in out and store.item(item)["thread"][-1]["kind"] == "info"


def test_an_agent_question_after_the_owner_message_answers_it(manager):
    store, item = _item(manager)
    store.post(item, "do the thing", actor="joe")
    assert call(manager, "task_manager_ask", {"item": item, "text": "which thing?"})[0]
    assert _reply(manager, item, text="fyi").get(owner_guards.STORED_AS_ANSWER_TO) is None


def test_a_review_handoff_after_the_owner_message_answers_it_but_a_system_move_does_not(manager):
    store, item = _item(manager)
    store.post(item, "please fix", actor="joe")
    with closing(store._connect(True)) as conn, conn:
        state_log.write(conn, item, "12", "open", "review", by=lineage.CARNIVORE, now=4.0e9)
    assert _reply(manager, item, text="fyi").get(owner_guards.STORED_AS_ANSWER_TO) is not None
    store.post(item, "and this", actor="joe")
    with closing(store._connect(True)) as conn, conn:
        state_log.write(conn, item, "12", "open", "review", by="uuid-s1", now=4.0e9)
    assert _reply(manager, item, text="fyi").get(owner_guards.STORED_AS_ANSWER_TO) is None


def test_a_files_only_owner_message_is_quoted_by_words_and_a_reply_with_files_stays_info(manager):
    store, item = _item(manager)
    asked = store.post(item, "", actor="joe", allow_blank=True, parts='{"files": []}')["message"]["id"]
    plan = owner_guards.plan_reply(store, item, None, True)
    assert (plan.kind, plan.quote, plan.quote_text, plan.notify) == ("answer", None, owner_guards.FILES_ONLY_QUOTE, False)
    assert "notify was dropped" in plan.said[owner_guards.GUARD_NOTE]
    kept = owner_guards.plan_reply(store, item, "info", False, has_files=True)
    assert kept.kind == "info" and f"message {asked} is still unanswered" in kept.said[owner_guards.GUARD_NOTE]


def test_an_explicit_answer_passes_through_untouched(manager):
    store, item = _item(manager)
    store.post(item, "q", actor="joe")
    plan = owner_guards.plan_reply(store, item, "answer", False, quote_text="asked in the terminal")
    assert plan == owner_guards.ReplyPlan("answer", None, "asked in the terminal", False, {})


def test_the_batch_reply_is_guarded_and_its_lean_answer_says_so(manager):
    store, item = _item(manager)
    asked = store.post(item, "ok?", actor="joe")["message"]["id"]
    ok, body = call(manager, "task_manager_batch_run", {"list_id": "12", "ops": [{"op": "reply", "item_id": item, "text": "yes"}]})
    assert ok and body["results"][0][owner_guards.STORED_AS_ANSWER_TO] == asked




def test_review_is_allowed_when_the_item_is_clean(manager):
    _, item = _item(manager)
    ok, out = _review(manager, item)
    assert ok and out["state"] == "review"


def test_review_is_refused_while_an_owner_message_is_unanswered_then_allowed_after_the_answer(manager):
    store, item = _item(manager)
    asked = store.post(item, "did it work?", actor="joe")["message"]["id"]
    ok, text = _review(manager, item)
    assert not ok and f"the owner's message {asked} is unanswered" in text and store.item(item)["state"] == "open"
    _reply(manager, item, text="yes, it works")
    assert _review(manager, item)[0]


@pytest.mark.parametrize("state", ["review", "done_by_claude"])
def test_review_and_its_legacy_name_are_both_guarded(manager, state):
    store, item = _item(manager)
    store.post(item, "q", actor="joe")
    ok, text = call(manager, "task_manager_update", {"item": item, "state": state})
    assert not ok and "not ready for review" in text


def test_review_is_refused_while_the_agents_own_question_is_open(manager):
    store, item = _item(manager)
    ok, asked = call(manager, "task_manager_ask", {"item": item, "text": "which one?"})
    assert ok
    ok, text = _review(manager, item)
    assert not ok and f"your question {asked['message_id']} is still open" in text


def test_review_is_refused_while_a_subtask_is_not_in_review_or_done(manager):
    store, item = _item(manager)
    ok, made = call(manager, "task_manager_fork", {"item": item, "title": "piece"})
    assert ok
    child = made["fork"]["item_id"]
    ok, text = _review(manager, item)
    assert not ok and f"1 subtask is not in review or done yet: {child} 'piece' (open)" in text
    store.update(child, actor="joe", approve=True)
    assert _review(manager, item)[0]


def test_review_is_refused_while_a_named_handoff_has_no_result_then_allowed(manager, handoff_root):
    store, item = _item(manager, f"queued: run ~/.handoff/handoff {HANDOFF}")
    ok, text = _review(manager, item)
    assert not ok and f"the handoff {HANDOFF} has not been run yet" in text
    (handoff_root / "log" / f"{HANDOFF}.result").write_text("step 1 RAN\n")
    assert _review(manager, item)[0]


def test_a_handoff_named_in_the_thread_by_its_script_path_counts(manager):
    store, item = _item(manager)
    _reply(manager, item, text=f"saved as ~/.handoff/pending/{HANDOFF}.sh")
    ok, text = _review(manager, item)
    assert not ok and HANDOFF in text


def test_the_handoff_check_fails_open_without_a_handoff_folder(manager, tmp_path, monkeypatch):
    monkeypatch.setattr(owner_guards, "HANDOFF_ROOT", tmp_path / "no-such-folder")
    _, item = _item(manager, f"run ~/.handoff/handoff {HANDOFF}")
    assert _review(manager, item)[0]


def test_handoff_names_resolve_through_one_helper(handoff_root):
    queue(handoff_root, "other-one")
    texts = [f"ssh -t mac-mini-m4 '~/.handoff/handoff {HANDOFF}.sh'", "~/.handoff/handoff show other-one.", "plain handoff talk"]
    assert owner_guards.pending_handoffs(texts) == sorted([HANDOFF, "other-one"])
    assert owner_guards.handoff_result(f"{HANDOFF}.sh") == handoff_root / "log" / f"{HANDOFF}.result"


def test_the_batch_update_and_the_fork_parent_state_are_guarded(manager):
    store, item = _item(manager)
    store.post(item, "q", actor="joe")
    ok, body = call(manager, "task_manager_batch_run", {"list_id": "12", "ops": [{"op": "update", "item_id": item, "state": "review"}]})
    assert ok and body["results"][0]["ok"] is False and "not ready for review" in body["results"][0]["error"]
    ok, text = call(manager, "task_manager_fork", {"item": item, "parent_state": "review"})
    assert not ok and "not ready for review" in text
    assert store.item(item)["state"] == "open"


def test_a_fork_born_in_review_is_guarded_by_its_copied_text(manager):
    _, item = _item(manager, f"run ~/.handoff/handoff {HANDOFF}")
    ok, text = call(manager, "task_manager_fork", {"item": item, "fork_state": "review"})
    assert not ok and HANDOFF in text


def test_the_owner_and_the_systems_attributed_moves_are_never_refused(manager):
    store, item = _item(manager, f"run ~/.handoff/handoff {HANDOFF}")
    store.post(item, "q", actor="joe")
    assert store.update(item, actor="joe", state="review")["state"] == "review"
    store.update(item, actor="joe", state="open")
    returned = store.update(item, actor="claude", state="review", decided=lineage.Decided(lineage.CARNIVORE, "turn ended unanswered, back"))
    assert returned["state"] == "review"
