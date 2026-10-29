
from __future__ import annotations

import asyncio
from contextlib import closing

import pytest

from src.cplugs.host import runtime
from src.cplugs.huddle import board, board_port, owner_guards, service
from src.cplugs.huddle.answer_writer import AnswerWriter
from src.cplugs.huddle.cards import state_log
from src.cplugs.huddle.roles import ask
from src.cplugs.huddle.rules import TaskManagerInvalid, TaskManagerLocked
from tests.python.cplugs.huddle.test_task_manager_mcp import call, huddle_store, manager  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_owner_guards import HANDOFF, _item, _reply, _review, handoff_root  # noqa: F401

ONE_LINER = f"run ~/.handoff/handoff {HANDOFF} to finish"


def _newest_move(store, item: int):
    with closing(store._connect(False)) as conn:
        return state_log.newest(conn, item)


def _in_review(manager, text: str = "work") -> tuple:
    store, item = _item(manager, text)
    ok, out = _review(manager, item)
    assert ok and out["state"] == "review", out
    return store, item




def test_an_agents_fork_with_parent_state_review_is_refused_by_its_own_new_fork(manager):
    store, item = _item(manager)
    with pytest.raises(TaskManagerLocked, match="1 subtask is not in review or done yet: .* 'split off' \\(open\\)"):
        store.fork(item, actor="claude", title="split off", parent_state="review")
    assert store.item(item)["state"] == "open"
    assert [i["id"] for i in store.list_items("12")["items"]] == [item]
    ok, text = call(manager, "task_manager_fork", {"item": item, "title": "split off", "parent_state": "review"})
    assert not ok and "subtask" in text


def test_an_agents_fork_of_an_item_in_review_withdraws_the_review(manager):
    store, item = _in_review(manager)
    made = store.fork(item, actor="claude", title="split off")
    assert made["parent"]["state"] == "open"
    move = _newest_move(store, item)
    assert move["by"] == "carnivore" and move["detail"].startswith(owner_guards.WITHDRAWN)




def test_a_carnivore_question_after_the_owner_message_does_not_answer_it(manager):
    store, item = _item(manager)
    asked = store.post(item, "why did this break?", actor="joe")["message"]["id"]
    ask.carnivore_ask(store, item, category=ask.STALL, context="idle 90 min", options=ask.STALL_OPTIONS)
    plan = owner_guards.plan_reply(store, item, None, False)
    assert (plan.kind, plan.quote) == ("answer", asked)
    with closing(store._connect(False)) as conn:
        reasons = owner_guards.review_blockers(conn, conn.execute("SELECT * FROM work_items WHERE id = ?", (item,)).fetchone())
    assert any(f"message {asked} is unanswered" in r for r in reasons) and not any("your question" in r for r in reasons)


def test_the_owners_submit_to_a_carnivore_question_keeps_his_earlier_words_in_view(manager):
    store, item = _item(manager)
    asked = store.post(item, "why did this break?", actor="joe")["message"]["id"]
    stall = ask.carnivore_ask(store, item, category=ask.STALL, context="idle 90 min", options=ask.STALL_OPTIONS)["message"]["id"]
    AnswerWriter(store).submit(stall, {"q1": {"choice": ask.UNSTICK}})
    assert owner_guards.plan_reply(store, item, None, False).quote == asked




def test_the_agents_question_on_an_item_in_review_withdraws_the_review(manager):
    store, item = _in_review(manager)
    assert call(manager, "task_manager_ask", {"item": item, "text": "which one?"})[0]
    assert store.item(item)["state"] == "open"
    assert _newest_move(store, item)["detail"] == f"{owner_guards.WITHDRAWN}: the agent asked a question"


def test_an_info_naming_a_queued_handoff_on_an_item_in_review_withdraws_the_review(manager):
    store, item = _in_review(manager)
    _reply(manager, item, text=f"queued: ~/.handoff/handoff {HANDOFF}")
    assert store.item(item)["state"] == "open"
    _, other = _in_review(manager, "second")
    _reply(manager, other, text="a plain fyi")
    assert store.item(other)["state"] == "review"


def test_a_carnivore_question_on_an_item_in_review_leaves_it_there(manager):
    store, item = _in_review(manager)
    store.post(item, "stalled?", actor="claude", kind="question", author_key="carnivore")
    assert store.item(item)["state"] == "review"




def test_a_handoff_named_only_in_the_review_description_refuses_review(manager):
    store, item = _item(manager)
    with pytest.raises(TaskManagerInvalid, match=HANDOFF):
        store.update(item, actor="claude", state="review", review_fields={"review_description": ONE_LINER})
    assert store.item(item)["state"] == "open"


def test_naming_a_queued_handoff_in_the_review_block_of_an_item_already_in_review_is_refused(manager, handoff_root):
    store, item = _in_review(manager)
    with pytest.raises(TaskManagerInvalid, match=HANDOFF):
        store.update(item, actor="claude", state="review", review_fields={"review_summary": ONE_LINER})
    (handoff_root / "log" / f"{HANDOFF}.result").write_text("step 1 RAN\n")
    assert store.update(item, actor="claude", state="review", review_fields={"review_summary": ONE_LINER})["state"] == "review"




def test_the_agent_closing_its_own_question_clears_b_on_purpose(manager):
    store, item = _item(manager)
    assert call(manager, "task_manager_ask", {"item": item, "text": "which one?"})[0]
    assert not _review(manager, item)[0]
    assert call(manager, "task_manager_answered_set", {"item": item})[0]
    assert _review(manager, item)[0]




def test_a_board_round_then_a_revision_card_can_request_review(manager):
    store, item = _item(manager)
    store.post(item, "round n2: tighten the header", actor="joe", parts=board.round_parts_of({"slug": "s", "round": "n2", "revision": "r1"}))
    assert owner_guards.plan_reply(store, item, None, False).kind is None
    port = board_port.BoardPort(runtime.host_for(manager.app).context("huddle"))
    out = asyncio.run(port.post_card(None, item, text="revision r2 is up", card={"slug": "s", "revision": "r2", "title": "t", "summary": "s"},
                                     request_review=True, review={"summary": "r2", "description": "r2 answers round n2", "where": "board s"},
                                     cross_project=False))
    assert out["review"]["moved"] is True and store.item(item)["state"] == "review"




def test_an_archived_handoff_and_a_prose_mention_are_not_pending(handoff_root):
    (handoff_root / "archive").mkdir()
    (handoff_root / "archive" / "20261006-declined.sh").write_text("#!/bin/bash\n")
    texts = ["the declined one was ~/.handoff/handoff 20261006-declined", "With no name, ~/.handoff/handoff opens the picker.",
             "~/.handoff/handoff on the mini"]
    assert owner_guards.pending_handoffs(texts) == []
    assert owner_guards.handoff_script(HANDOFF) == handoff_root / "pending" / f"{HANDOFF}.sh"


def test_an_item_naming_a_declined_handoff_can_reach_review(manager):
    _, item = _item(manager, "was ~/.handoff/handoff 20261006-declined, declined")
    assert _review(manager, item)[0]




def test_a_cross_project_info_stays_info_and_the_owning_agent_must_still_answer(manager, monkeypatch):
    monkeypatch.setattr(service, "project_names", lambda ctx: {"12": "Carnivore", "7": "Blog"})
    store = huddle_store(manager)
    item = store.add("7", "blog work", actor="joe")["id"]
    asked = store.post(item, "did the deploy finish?", actor="joe")["message"]["id"]
    ok, out = call(manager, "task_manager_reply", {"item": item, "text": "fyi from carnivore", "cross_project": True}, raw=True)
    assert ok and owner_guards.STORED_AS_ANSWER_TO not in out
    assert [m["kind"] for m in store.item(item)["thread"] if m["text"] == "fyi from carnivore"] == ["info"]
    with pytest.raises(TaskManagerInvalid, match=f"message {asked} is unanswered"):
        store.update(item, actor="claude", state="review")

