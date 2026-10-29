
from __future__ import annotations

from src.cplugs.huddle import slim


def msg(id_: int, author: str = "claude", kind: str = "info", **extra):
    return {"id": id_, "author": author, "kind": kind, "answered": False, "unread": False, **extra}


def ids(thread):
    return [m["id"] for m in thread]


def test_old_read_posts_are_dropped_and_the_newest_is_the_preview():
    thread = [msg(i) for i in range(1, 6)]
    assert ids(slim.slim_thread(thread)) == [5]


def test_open_questions_unread_posts_and_joes_newest_reply_stay():
    thread = [msg(1), msg(2, kind="question"), msg(3, "joe", "reply"), msg(4, kind="attention", unread=True),
              msg(5, "joe", "reply"), msg(6), msg(7, kind="question")]
    assert ids(slim.slim_thread(thread)) == [2, 4, 5, 7]


def test_the_newest_question_stays_even_answered_and_so_does_its_stored_answer():
    thread = [msg(1, kind="question", answered=True), msg(2, "joe", "form_answer", answers_to=1), msg(3), msg(4)]
    assert ids(slim.slim_thread(thread)) == [1, 2, 4]


def test_a_nudge_is_never_the_preview():
    thread = [msg(1), msg(2, category=slim.NUDGE_CATEGORY)]
    assert ids(slim.slim_thread(thread)) == [1]


def test_slim_item_counts_the_full_thread_and_leaves_the_input_alone():
    item = {"id": 9, "thread": [msg(1), msg(2), msg(3)]}
    out = slim.slim_item(item)
    assert out["thread_count"] == 3 and out["thread_slim"] is True and ids(out["thread"]) == [3]
    assert len(item["thread"]) == 3 and "thread_slim" not in item


def test_a_kept_form_answer_brings_its_question():
    thread = [msg(1, kind="question", answered=True), msg(2, kind="question", answered=True), msg(3, "joe", "reply", answers_to=1), msg(4)]
    assert ids(slim.slim_thread(thread)) == [1, 2, 3, 4]


def test_the_newest_agent_answer_and_the_question_it_quotes_stay_for_the_review_card():
    thread = [msg(1, "joe", "reply"), msg(2, kind="answer", quote={"id": 1, "text": "q"}), msg(3), msg(4)]
    assert ids(slim.slim_thread(thread)) == [1, 2, 4]
