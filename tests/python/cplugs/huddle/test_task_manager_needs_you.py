
from __future__ import annotations

from src.cplugs.huddle import lifecycle, review
from src.cplugs.huddle.rules import JOE
from src.cplugs.huddle.store import TaskManagerStore
from tests.python.cplugs.huddle.test_task_manager_mcp import call, manager  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_sections import store


def flagged(s: TaskManagerStore) -> set:
    return {i["id"] for i in s.list_items("all")["items"] if i["needs_you"]}


def old_look(s: TaskManagerStore, item: int, text: str, action: str | None = None) -> dict:
    return s.post(item, text, actor="claude", kind="attention", parts=review.look_parts(action))["message"]


def test_needs_you_rule_is_a_flag_not_a_status():
    assert lifecycle.needs_you("question") and lifecycle.needs_you("working", None, "tick") and not lifecycle.needs_you("working", None, "read")
    assert not lifecycle.needs_you("review") and not lifecycle.needs_you("review", "push", "tick")
    assert not lifecycle.needs_you("working") and not lifecycle.needs_you("open") and not lifecycle.needs_you("waiting")
    assert not lifecycle.needs_you("working", None, "none") and not lifecycle.needs_you("open", "push", None)
    assert not lifecycle.needs_you("done", "tick", "read") and not lifecycle.needs_you("done", None, "tick")
    assert "needs_you" not in lifecycle.STATUSES and "needs_you" not in lifecycle.SECTIONS


def test_membership_keeps_status_and_section_and_counts_in_the_summary(manager):
    s = store(manager, lifecycle.VIEW_STATUS)
    ok, plain = call(manager, "task_manager_add", {"list": "all", "text": "plain"})
    ok, asked = call(manager, "task_manager_add", {"list": "all", "text": "ask", "kind": "question"})
    ok, done = call(manager, "task_manager_add", {"list": "all", "text": "built"})
    call(manager, "task_manager_update", {"item": done["id"], "state": "review"})
    ok, look = call(manager, "task_manager_add", {"list": "all", "text": "look at me"})
    call(manager, "task_manager_update", {"item": look["id"], "state": "working"})
    old_look(s, look["id"], "see this", "tick")
    ok, fyi = call(manager, "task_manager_add", {"list": "all", "text": "fyi look"})
    call(manager, "task_manager_update", {"item": fyi["id"], "state": "working"})
    old_look(s, fyi["id"], "plain look")
    assert flagged(s) == {asked["id"], look["id"]}
    by_id = {i["id"]: i for i in s.list_items("all")["items"]}
    assert (by_id[look["id"]]["status"], by_id[look["id"]]["section"]) == ("open", "open")
    assert (by_id[asked["id"]]["section"], by_id[done["id"]]["section"]) == ("question", "review")
    assert s.summary()["lists"]["all"]["needs_you"] == 2
    assert {i: by_id[i]["number"] for i in by_id if i in (asked["id"], look["id"])}.keys() == {asked["id"], look["id"]}
    assert by_id[plain["id"]]["number"] == 4
    assert (by_id[asked["id"]]["needs_action"], by_id[done["id"]]["needs_action"], by_id[look["id"]]["needs_action"]) == ("answer", None, "tick")
    assert by_id[plain["id"]]["needs_action"] is None and by_id[fyi["id"]]["needs_action"] is None
    call(manager, "task_manager_update", {"item": done["id"], "review_action": "push"})
    assert s.item(done["id"])["needs_action"] is None and not s.item(done["id"])["needs_you"]
    ok, bad = call(manager, "task_manager_reply", {"item": look["id"], "text": "x", "kind": "info", "action": "read"})
    assert not ok
    ok, bad = call(manager, "task_manager_reply", {"item": look["id"], "text": "x", "kind": "attention", "action": "go"})
    assert not ok
    ok, bad = call(manager, "task_manager_reply", {"item": look["id"], "text": "x", "kind": "attention", "action": "tick"})
    assert not ok and "task_manager_update" in bad


def test_the_flag_drops_on_answer_read_tick_and_delete(manager):
    s = store(manager, lifecycle.VIEW_STATUS)
    ok, asked = call(manager, "task_manager_add", {"list": "all", "text": "ask", "kind": "question"})
    ok, look = call(manager, "task_manager_add", {"list": "all", "text": "look", "kind": "question"})
    ok, review = call(manager, "task_manager_add", {"list": "all", "text": "built"})
    call(manager, "task_manager_update", {"item": review["id"], "state": "review"})
    ok, gone = call(manager, "task_manager_add", {"list": "all", "text": "doomed", "kind": "question"})
    s.post(look["id"], "answer", actor=JOE)
    old_look(s, look["id"], "see this", "tick")
    assert flagged(s) == {asked["id"], look["id"], gone["id"]} and review["id"] not in flagged(s)
    s.post(asked["id"], "my answer", actor=JOE)
    assert asked["id"] not in flagged(s)
    msg = next(m for m in s.item(look["id"])["thread"] if m["kind"] == "attention")
    s.mark_seen(look["id"], msg["id"])
    assert look["id"] not in flagged(s)
    s.update(review["id"], actor=JOE, state="done")
    assert review["id"] not in flagged(s)
    s.delete(gone["id"], actor=JOE)
    assert gone["id"] not in flagged(s) and flagged(s) == set()
    assert s.summary()["lists"]["all"]["needs_you"] == 0


def test_an_old_look_with_action_is_attention_and_a_file_at_rung_19_upgrades_idempotently(manager, tmp_path):
    import sqlite3
    from src.core.work.ladder import MIGRATIONS, SCHEMA_VERSION
    from src.core.work.storage import WorkStorage
    s = store(manager, lifecycle.VIEW_STATUS)
    ok, item = call(manager, "task_manager_add", {"list": "all", "text": "work"})
    call(manager, "task_manager_update", {"item": item["id"], "state": "working"})
    assert call(manager, "task_manager_reply", {"item": item["id"], "text": "check this", "action": "push"})[0] is False
    assert old_look(s, item["id"], "check this", "push")["kind"] == "attention" and s.item(item["id"])["needs_action"] == "push"
    path = tmp_path / "old" / "huddle.db"
    path.parent.mkdir()
    with sqlite3.connect(path) as conn:
        for step in MIGRATIONS[:19]:
            conn.executescript(step)
        conn.execute("INSERT INTO items (list_key, text, position, created_by, state, created_at, updated_at, created_seq, seq) "
                     "VALUES ('all', 'old', 0, 'joe', 'open', 1, 1, 1, 1)")
        conn.execute("PRAGMA user_version = 19")
    for _ in range(2):
        upgraded = TaskManagerStore(WorkStorage(path.parent), notify=lambda t: None)
        row = upgraded.list_items("all")["items"][0]
        assert (row["review_action"], row["needs_action"]) == (None, None)
        with sqlite3.connect(path) as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION



def test_a_read_or_none_look_stays_out_of_needs_you_while_answer_tick_and_push_land_in_it():
    for action in ("read", "none", None):
        assert lifecycle.needs_action("working", None, action) is None and not lifecycle.needs_you("working", None, action)
    for action in ("answer", "tick", "push"):
        assert lifecycle.needs_action("working", None, action) == action and lifecycle.needs_you("working", None, action)
    assert lifecycle.needs_action("question") == "answer"
    assert lifecycle.needs_action("review", None, "tick") is None
    assert lifecycle.needs_action("open", None, "read") is None


def test_an_info_flags_the_item_as_a_read_and_an_old_read_look_marks_it_unread_without_flagging_it(manager):
    s = store(manager, lifecycle.VIEW_STATUS)
    ok, item = call(manager, "task_manager_add", {"list": "all", "text": "work"})
    call(manager, "task_manager_update", {"item": item["id"], "state": "working"})
    ok, posted = call(manager, "task_manager_reply", {"item": item["id"], "text": "have a look", "action": "read", "lean": False})
    row = s.item(item["id"])
    assert ok and posted["kind"] == "info" and row["unread"] and row["needs_you"] and row["needs_action"] == "read"
    ok, old = call(manager, "task_manager_add", {"list": "all", "text": "older"})
    old_look(s, old["id"], "have a look", "read")
    row = s.item(old["id"])
    assert row["unread"] and not row["needs_you"] and row["needs_action"] is None
    assert s.summary()["lists"]["all"]["needs_you"] == 1
