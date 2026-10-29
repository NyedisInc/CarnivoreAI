
from __future__ import annotations

import pytest

from src.cplugs.huddle import lifecycle, lineage, question_cancel, triggers
from src.cplugs.huddle.rules import TaskManagerInvalid
from tests.python.cplugs.huddle.test_task_manager_lifecycle import tell
from tests.python.cplugs.huddle.test_task_manager_mcp import call, huddle_store, manager  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note, row  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_schedule import ITEMS, env, iso  # noqa: F401


def moves(store, item_id):
    from contextlib import closing

    with closing(store._connect(False)) as conn:
        return [(r["from"], r["to"], r["by"], r["detail"]) for r in lineage.for_item(conn, item_id)]


def test_an_agent_move_past_an_uncleared_blocker_stops_in_waiting_and_joes_never_does(manager):  # noqa: F811
    store = huddle_store(manager)
    item = store.add("all", "split it", actor="joe")["id"]
    child = store.fork(item, actor="claude", parent_waits=True)["fork"]["id"]
    ok, moved = call(manager, "task_manager_update", {"item": item, "state": "review"})
    assert ok and store.item(item)["state"] == "waiting"
    assert moves(store, item)[-1] == ("waiting", "waiting", "carnivore", "blocked")
    store.update(item, actor="joe", state="open")
    assert store.item(item)["state"] == "open" and "blockers" not in store.item(item)
    store.update(child, actor="joe", state="done")
    ok, _ = call(manager, "task_manager_update", {"item": item, "state": "review"})
    assert ok and store.item(item)["state"] == "review"


def test_a_task_is_born_open_or_todo_and_never_anywhere_else(manager):  # noqa: F811
    store = huddle_store(manager)
    ok, added = call(manager, "task_manager_add", {"list": "all", "text": "later", "state": "back_burner"}, raw=True)
    assert ok and store.item(added["item_id"])["state"] == "todo"
    assert moves(store, added["item_id"])[0][:2] == ("", "todo") and moves(store, added["item_id"])[0][3] == "born"
    with pytest.raises(TaskManagerInvalid):
        store.add("all", "x", actor="joe", state="review")
    parked = store.add("all", "y", actor="joe", state="todo")["id"]
    store.update(parked, actor="joe", state="open")
    assert [m[:2] for m in moves(store, parked)] == [("", "todo"), ("todo", "open")]


def test_a_new_question_supersedes_the_open_one(manager):  # noqa: F811
    store = huddle_store(manager)
    item = store.add("all", "decide", actor="joe")["id"]
    assert call(manager, "task_manager_ask", {"item": item, "text": "first?"})[0]
    assert call(manager, "task_manager_ask", {"item": item, "text": "second?"})[0]
    asks = [m for m in store.item(item)["thread"] if m["kind"] == "question"]
    assert [m["answered"] for m in asks] == [True, False] and asks[0]["superseded"] is True and "superseded" not in asks[1]
    assert store.summary()["lists"]["all"]["questions"] == 1


def test_an_answer_goes_to_open_and_a_cancel_goes_to_open_with_a_note(manager):  # noqa: F811
    store = huddle_store(manager)
    answered = store.add("all", "a", actor="joe")["id"]
    call(manager, "task_manager_update", {"item": answered, "state": "review"})
    call(manager, "task_manager_ask", {"item": answered, "text": "which one?"})
    assert store.post(answered, "the second", actor="joe")["item"]["state"] == "open"
    cancelled = store.add("all", "b", actor="joe")["id"]
    call(manager, "task_manager_update", {"item": cancelled, "state": "waiting", "waiting_on": "the staging restart", "wait_kind": "install"})
    call(manager, "task_manager_ask", {"item": cancelled, "text": "shall i?"})
    after = question_cancel.cancel(store, cancelled)
    assert after["state"] == "open" and after["status"] != "question" and [m["text"] for m in after["thread"] if not m.get("category")][-1] == question_cancel.CANCEL_NOTE
    with pytest.raises(TaskManagerInvalid):
        question_cancel.cancel(store, cancelled)


def test_a_cancel_route_reopens_the_task(client, app):  # noqa: F811
    from src.cplugs.host import runtime
    from src.cplugs.huddle.store import TaskManagerStore

    created = client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "ask me"}).json()["id"]
    store = TaskManagerStore(runtime.host_for(app).storage("huddle"), notify=lambda key: None)
    store.post(created, "ok?", actor="claude", kind="question")
    reply = client.post(f"/api/v1/cplugs/huddle/items/{created}/cancel-question")
    assert reply.status_code == 200 and reply.json()["state"] == "open" and reply.json()["status"] != "question"
    assert client.post(f"/api/v1/cplugs/huddle/items/{created}/cancel-question").status_code == 400


def test_the_owners_reply_on_a_review_opens_it_and_the_answer_returns_it_to_review(manager):  # noqa: F811
    store = huddle_store(manager)
    item = store.add("all", "work", actor="joe")["id"]
    call(manager, "task_manager_update", {"item": item, "state": "review"})
    store.post(item, "why this approach?", actor="joe")
    assert store.item(item)["state"] == "open"
    assert moves(store, item)[-1] == ("review", "open", "owner", "joe replied")
    assert store.awaiting_answer([item]) == [item]
    ok, _ = call(manager, "task_manager_reply", {"item": item, "text": "because of the limit", "kind": "info", "changes": True})
    assert ok and store.item(item)["state"] == "open" and store.awaiting_answer([item]) == []
    assert call(manager, "task_manager_update", {"item": item, "state": "review"})[0]
    last = moves(store, item)[-1]
    assert last[:2] == ("open", "review") and last[2] != "owner" and last[3] == "answered, back to review"


def test_changes_keep_the_task_open_and_a_bare_review_is_refused_until_answered(manager):  # noqa: F811
    store = huddle_store(manager)
    item = store.add("all", "work", actor="joe")["id"]
    call(manager, "task_manager_update", {"item": item, "state": "review"})
    store.post(item, "also rename it", actor="joe")
    ok, text = call(manager, "task_manager_update", {"item": item, "state": "review"})
    assert not ok and "unanswered" in text and store.item(item)["state"] == "open"
    assert call(manager, "task_manager_reply", {"item": item, "text": "renamed"})[0]
    assert call(manager, "task_manager_update", {"item": item, "state": "review"})[0]
    assert moves(store, item)[-1][3] == "answered, back to review"


def test_the_owners_reply_on_a_done_task_opens_it_and_the_session_restores_done_without_a_tick(manager):  # noqa: F811
    store = huddle_store(manager)
    done = store.add("all", "finished", actor="joe")["id"]
    store.update(done, actor="joe", approve=True)
    ok, text = call(manager, "task_manager_update", {"item": done, "state": "done"})
    assert not ok
    store.post(done, "what did you change?", actor="joe")
    assert store.item(done)["state"] == "open" and moves(store, done)[-1] == ("done", "open", "owner", "joe replied")
    ok, _ = call(manager, "task_manager_update", {"item": done, "state": "done"})
    assert not ok and store.item(done)["state"] == "open"
    assert call(manager, "task_manager_reply", {"item": done, "text": "only the title", "kind": "info"})[0]
    assert call(manager, "task_manager_update", {"item": done, "state": "done"})[0]
    last = moves(store, done)[-1]
    assert store.item(done)["state"] == "done" and last[:2] == ("open", "done") and last[2] != "owner" and last[3] == "answered, back to done"
    ok, _ = call(manager, "task_manager_update", {"item": done, "state": "open"})
    assert not ok


def test_an_agent_cannot_restore_done_on_a_task_that_was_not_reopened_by_a_reply(manager):  # noqa: F811
    store = huddle_store(manager)
    item = store.add("all", "w", actor="joe")["id"]
    store.update(item, actor="joe", approve=True)
    store.update(item, actor="joe", state="open")
    store.post(item, "note to self", actor="claude", kind="info")
    ok, _ = call(manager, "task_manager_update", {"item": item, "state": "done"})
    assert not ok


def test_claude_parks_freely_and_joe_releases(manager):  # noqa: F811
    store = huddle_store(manager)
    item = store.add("all", "later", actor="joe")["id"]
    ok, _ = call(manager, "task_manager_update", {"item": item, "state": "todo"})
    assert ok and store.item(item)["state"] == "todo"
    store.update(item, actor="joe", state="open")
    assert store.item(item)["state"] == "open" and moves(store, item)[-1][:2] == ("todo", "open")


def test_untick_goes_back_to_the_state_before_the_close(manager):  # noqa: F811
    store = huddle_store(manager)
    item = store.add("all", "w", actor="joe")["id"]
    call(manager, "task_manager_update", {"item": item, "state": "review"})
    store.update(item, actor="joe", approve=True)
    assert store.update(item, actor="joe", approve=False)["state"] == "review"


def test_ticking_a_repeating_task_returns_it_to_scheduled_and_a_one_time_one_goes_done(client, env):  # noqa: F811
    from tests.python.cplugs.huddle.test_task_manager_recurring import DAILY, repeat_item

    repeating = repeat_item(client, env)
    env.store.update(repeating["id"], actor="claude", state="review")
    ticked = client.patch(f"{ITEMS}/{repeating['id']}", json={"approved": True}).json()
    assert ticked["state"] == "open" and ticked["status"] == "scheduled" and ticked["start_trigger"]["repeat"] == DAILY
    assert moves(env.store, repeating["id"])[-1][2:] == ("owner", "repeat_tick")
    single = env.add(client, text="one time")
    assert client.patch(f"{ITEMS}/{single['id']}", json={"approved": True}).json()["state"] == "done"


def test_a_fire_on_a_waiting_task_is_delivered_and_release_resumes_a_parked_one(client, env):  # noqa: F811
    note(env.app, "ses_new", "12", 100.0)
    waiting = env.add(client, text="waits")
    client.patch(f"{ITEMS}/{waiting['id']}", json={"fire_at": iso(3600)})
    env.store.update(waiting["id"], actor="claude", state="waiting")
    env.overdue(waiting["id"])
    assert [i["id"] for i in env.store.claim_due_triggers()] == [waiting["id"]]
    assert env.trigger(waiting["id"])["last_error"] is None
    parked = env.add(client, text="parked")
    client.patch(f"{ITEMS}/{parked['id']}", json={"fire_at": iso(3600)})
    client.patch(f"{ITEMS}/{parked['id']}", json={"state": "todo"})
    with env.ctx.storage.connect(True) as conn:
        conn.execute("UPDATE work_item_triggers SET fired_at = fire_at, last_error = ? WHERE item_id = ?", (triggers.SKIP_PARKED, parked["id"]))
    client.patch(f"{ITEMS}/{parked['id']}", json={"state": "open"})
    assert [i["id"] for i in env.store.claim_due_triggers()] == [parked["id"]]


def test_attention_counts_questions_plus_reviews_only(manager):  # noqa: F811
    store = huddle_store(manager)
    asked, reviewing, plain, parked = (store.add("all", t, actor="claude")["id"] for t in ("q", "r", "p", "t"))
    call(manager, "task_manager_ask", {"item": asked, "text": "which?"})
    call(manager, "task_manager_update", {"item": reviewing, "state": "review"})
    call(manager, "task_manager_update", {"item": parked, "state": "todo"})
    row_ = store.summary()["lists"]["all"]
    assert row_["attention"] == 2
    store.update(reviewing, actor="joe", approve=True)
    assert store.summary()["lists"]["all"]["attention"] == 1


def test_status_counts_feed_the_badge_menu(manager):  # noqa: F811
    store = huddle_store(manager)
    asked, reviewing, plain, parked, waiting = (store.add("all", t, actor="claude")["id"] for t in ("q", "r", "p", "t", "w"))
    call(manager, "task_manager_ask", {"item": asked, "text": "which?"})
    call(manager, "task_manager_update", {"item": reviewing, "state": "review"})
    call(manager, "task_manager_update", {"item": parked, "state": "todo"})
    store.update(waiting, actor="claude", state="waiting")
    counts = store.summary()["lists"]["all"]["status_counts"]
    assert counts == {"question": 1, "review": 1, "open": 1, "waiting": 1}
    assert counts["question"] + counts["review"] == store.summary()["lists"]["all"]["attention"]
