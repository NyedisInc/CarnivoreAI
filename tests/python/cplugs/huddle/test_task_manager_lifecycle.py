
from __future__ import annotations

import sqlite3

from src.core.work.ladder import feature_rungs
from src.cplugs.huddle import lifecycle
from src.cplugs.huddle.rules import CLAUDE, JOE
from tests.python.cplugs.huddle.test_task_manager_mcp import call, huddle_store, manager  # noqa: F401
from src.core.mcp.caller import AgentCaller


def status(manager, item_id):
    return huddle_store(manager).item(item_id)["status"]


def tell(manager, *lists):
    store = huddle_store(manager)
    store.record_send(list(lists), store.current_cursor())


def test_claude_item_is_open_then_review_when_done(manager):
    ok, item = call(manager, "task_manager_add", {"list": "all", "text": "a thing"})
    assert ok and item["status"] == "open"
    ok, item = call(manager, "task_manager_update", {"item": item["id"], "state": "review"})
    assert item["status"] == "review"


def test_a_question_waits_on_joe_and_his_reply_waits_to_send(manager):
    store = huddle_store(manager)
    ok, item = call(manager, "task_manager_add", {"list": "all", "text": "a thing"})
    call(manager, "task_manager_ask", {"item": item["id"], "text": "which one?"})
    assert status(manager, item["id"]) == "question"
    store.post(item["id"], "the second", actor=JOE, kind="reply")
    assert status(manager, item["id"]) == "waiting_to_send"


def test_claude_question_kind_item_waits_on_joe_until_he_touches_it(manager):
    item = huddle_store(manager).add("all", "need your call", actor="claude", kind="question")
    assert item["status"] == "question"
    huddle_store(manager).update(item["id"], actor=JOE, note="go")
    assert status(manager, item["id"]) == "waiting_to_send"


def test_joe_item_waits_to_send_until_an_mcp_read_returns_it_then_open_without_a_tell(manager):
    added = huddle_store(manager).add("all", "fix it", actor=JOE)
    assert added["status"] == "waiting_to_send"
    assert huddle_store(manager).summary()["lists"]["all"]["waiting_to_send"] == 1
    ok, listed = call(manager, "task_manager_tasks_list", {"list": "all"})
    assert [i["status"] for i in listed["items"]] == ["open"]
    assert status(manager, added["id"]) == "open"
    assert huddle_store(manager).summary()["lists"]["all"]["waiting_to_send"] == 0


def test_a_told_change_that_claude_reads_stays_open(manager):
    added = huddle_store(manager).add("all", "fix it", actor=JOE)
    tell(manager, "all")
    assert status(manager, added["id"]) == "open"
    ok, listed = call(manager, "task_manager_tasks_list", {"list": "all"})
    assert [i["status"] for i in listed["items"]] == ["open"] and status(manager, added["id"]) == "open"


def test_a_claude_post_ends_working_and_after_he_reads_it_the_item_is_open_unless_claude_started_it(manager):
    store = huddle_store(manager)
    item = store.add("all", "fix attention", actor=JOE)
    tell(manager, "all")
    call(manager, "task_manager_update", {"item": item["id"], "state": "working"})
    assert status(manager, item["id"]) == "working"
    store.post(item["id"], "an fyi", actor=CLAUDE, kind="info")
    assert status(manager, item["id"]) == "working"
    store.post(item["id"], "a finding", actor=CLAUDE, kind="attention")
    assert status(manager, item["id"]) == "open"
    asked_now = store.add("all", "claude asks mid-way", actor=JOE)
    tell(manager, "all")
    call(manager, "task_manager_tasks_list", {"list": "all"})
    call(manager, "task_manager_ask", {"item": asked_now["id"], "text": "which?"})
    store.mark_answered(asked_now["id"], actor=JOE)
    assert status(manager, asked_now["id"]) == "open"
    started = store.add("all", "claude takes it", actor=JOE)
    call(manager, "task_manager_update", {"item": started["id"], "state": "working"})
    store.post(started["id"], "halfway", actor=CLAUDE, kind="info")
    assert status(manager, started["id"]) == "working"
    asked = store.add("all", "ask about it", actor=JOE)
    tell(manager, "all")
    call(manager, "task_manager_tasks_list", {"list": "all"})
    call(manager, "task_manager_ask", {"item": asked["id"], "text": "which one?"})
    assert status(manager, asked["id"]) == "question"
    store.mark_answered(asked["id"], actor=JOE)
    assert status(manager, asked["id"]) == "open"
    call(manager, "task_manager_ask", {"item": asked["id"], "text": "and this?"})
    store.post(asked["id"], "the second", actor=JOE, kind="reply")
    assert status(manager, asked["id"]) == "waiting_to_send"
    tell(manager, "all")
    call(manager, "task_manager_tasks_list", {"list": "all"})
    assert status(manager, asked["id"]) == "open"


def test_huddle_changes_is_a_read_too_and_a_later_change_waits_again(manager):
    store = huddle_store(manager)
    item = store.add("all", "fix it", actor=JOE)
    tell(manager, "all")
    ok, changed = call(manager, "task_manager_changes", {"since": 0})
    assert ok and status(manager, item["id"]) == "open"
    store.update(item["id"], actor=JOE, note="also this")
    assert status(manager, item["id"]) == "waiting_to_send"
    tell(manager, "all")
    call(manager, "task_manager_changes", {"since": changed["cursor"]})
    assert status(manager, item["id"]) == "open"


def test_huddle_focus_records_the_read_of_the_rows_it_points_at(manager):
    store = huddle_store(manager)
    a = store.add("12", "one", actor=JOE)
    b = store.add("12", "two", actor=JOE)
    tell(manager, "12")
    store.update(b["id"], actor=JOE, note="after the tell")
    ok, _ = call(manager, "huddle_focus", {"list": "12", "items": [a["id"]]})
    assert ok and status(manager, a["id"]) == "open" and status(manager, b["id"]) == "waiting_to_send"


def test_a_change_after_the_read_stays_waiting(manager):
    store = huddle_store(manager)
    item = store.add("all", "fix it", actor=JOE)
    stale_seq = item["seq"]
    store.update(item["id"], actor=JOE, note="more")
    store.record_claude_read([(item["id"], stale_seq)])
    assert status(manager, item["id"]) == "waiting_to_send"


def test_update_working_explicitly_and_done_clears_it(manager):
    ok, item = call(manager, "task_manager_add", {"list": "all", "text": "mine"})
    ok, item = call(manager, "task_manager_update", {"item": item["id"], "state": "working"})
    assert ok and item["status"] == "working" and item["state"] == "open"
    ok, item = call(manager, "task_manager_update", {"item": item["id"], "state": "review"})
    assert item["status"] == "review"
    ok, item = call(manager, "task_manager_update", {"item": item["id"], "state": "working"})
    assert item["state"] == "open" and item["status"] == "working"


def test_ticked_items_wear_the_completed_status(manager):
    store = huddle_store(manager)
    item = store.add("all", "ship", actor=JOE)
    call(manager, "task_manager_changes", {"since": 0})
    assert store.update(item["id"], actor=JOE, approve=True)["status"] == "waiting_to_send"
    call(manager, "task_manager_tasks_list", {"list": "all"})
    assert status(manager, item["id"]) == "done"
    store.update(item["id"], actor=JOE, note="with this")
    call(manager, "task_manager_tasks_list", {"list": "all"})
    assert status(manager, item["id"]) == "done"
    ok, text = call(manager, "task_manager_update", {"item": item["id"], "state": "working"})
    assert not ok


def test_an_external_token_read_records_nothing(manager):
    item = huddle_store(manager).add("all", "fix it", actor=JOE)
    external = AgentCaller("mcp-token:t", "mcp-token:t", "mcp-token:t", "tok", "read")
    ok, _ = call(manager, "task_manager_tasks_list", {"list": "all"}, caller=external)
    assert ok and status(manager, item["id"]) == "waiting_to_send"


def test_status_rungs_are_ordered():
    base = {"state": "open", "kind": "", "created_by": JOE, "joe_seq": 0, "claude_read_seq": 0, "claude_working": 0}
    assert lifecycle.status(base, False) == "open"
    assert lifecycle.status({**base, "joe_seq": 4}, True) == "question"
    assert lifecycle.status({**base, "joe_seq": 4, "state": "review"}, False) == "waiting_to_send"
    assert lifecycle.status({**base, "joe_seq": 4, "claude_read_seq": 4, "state": "review"}, False) == "review"
    assert lifecycle.status({**base, "joe_seq": 4, "claude_read_seq": 4}, False) == "open"
    assert lifecycle.status({**base, "joe_seq": 4, "told_seq": 5}, False) == "open"
    assert lifecycle.status({**base, "joe_seq": 4, "told_seq": 5, "claude_read_seq": 4}, False) == "open"
    assert lifecycle.status({**base, "claude_working": 1}, False) == "working"
    assert lifecycle.status({**base, "state": "waiting"}, False) == "waiting"
    assert lifecycle.status({**base, "state": "waiting", "joe_seq": 4}, False) == "waiting_to_send"
    assert lifecycle.status({**base, "state": "waiting", "claude_working": 1}, False) == "waiting"
    assert lifecycle.status({**base, "state": "done", "joe_seq": 9}, True) == "waiting_to_send"
    assert lifecycle.status({**base, "state": "done", "joe_seq": 9, "claude_read_seq": 9}, True) == "done"


def test_rung_six_counts_old_items_read_up_to_the_newest_session_cursor(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        "CREATE TABLE items (id INTEGER PRIMARY KEY, list_key TEXT, joe_seq INTEGER NOT NULL DEFAULT 0);"
        "CREATE TABLE reads (session_id TEXT, list_key TEXT, cursor INTEGER);"
        "INSERT INTO items VALUES (1, 'all', 3), (2, 'all', 9), (3, '12', 2);"
        "INSERT INTO reads VALUES ('s', 'all', 5);")
    conn.executescript(feature_rungs.LIFECYCLE_MIGRATION)
    assert dict(conn.execute("SELECT id, claude_read_seq FROM items")) == {1: 3, 2: 0, 3: 0}


def test_a_tick_and_an_untick_each_add_a_tell_until_claude_reads_them(manager):
    store = huddle_store(manager)
    item = store.add("all", "ship", actor=JOE)
    call(manager, "task_manager_tasks_list", {"list": "all"})
    assert store.summary()["lists"]["all"]["waiting_to_send"] == 0
    store.update(item["id"], actor=JOE, approve=True)
    row = store.summary()["lists"]["all"]
    assert row["waiting_to_send"] == 1 and row["untold"]
    call(manager, "task_manager_tasks_list", {"list": "all"})
    assert store.summary()["lists"]["all"]["waiting_to_send"] == 0
    assert status(manager, item["id"]) == "done"
    store.update(item["id"], actor=JOE, approve=False)
    assert store.summary()["lists"]["all"]["waiting_to_send"] == 1
    assert status(manager, item["id"]) == "waiting_to_send"


def _in_review(manager):
    ok, item = call(manager, "task_manager_add", {"list": "all", "text": "ship it"})
    ok, item = call(manager, "task_manager_update", {
        "item": item["id"], "state": "review", "review_description": "check the thing"})
    assert ok and item["status"] == "review"
    return item["id"]


def test_an_owner_reply_on_a_review_item_opens_it_and_the_session_returns_it_to_review(manager):
    item_id = _in_review(manager)
    replied = huddle_store(manager).post(item_id, "not quite, more work", actor=JOE, kind="reply")["item"]
    assert replied["state"] == "open" and replied["status"] == "waiting_to_send"
    assert replied["review_description"] == "check the thing"
    tell(manager, "all")
    ok, read = call(manager, "task_manager_changes", {"since": 0})
    assert ok and read["owner_replied"] == [item_id] and "answer" in read["owner_replied_do"]
    assert status(manager, item_id) != "review"
    ok, item = call(manager, "task_manager_reply", {"item": item_id, "text": "more work, on it", "kind": "info"})
    ok, item = call(manager, "task_manager_update", {"item": item_id, "state": "review"})
    assert item["status"] == "review" and item["review_description"] == "check the thing"


def test_a_claude_reply_leaves_review_as_review(manager):
    item_id = _in_review(manager)
    for kind in ("info", "attention"):
        huddle_store(manager).post(item_id, "fyi", actor=CLAUDE, kind=kind)
        assert huddle_store(manager).item(item_id)["state"] == "review"
        assert status(manager, item_id) == "review"
        huddle_store(manager).mark_seen(item_id)
        assert status(manager, item_id) == "review"


def test_a_tick_on_a_review_item_is_still_an_approval(manager):
    item_id = _in_review(manager)
    ticked = huddle_store(manager).update(item_id, actor=JOE, approve=True)
    assert ticked["state"] == "done"


def test_an_unread_look_or_info_never_changes_the_status():
    base = {"state": "review", "kind": "", "created_by": JOE, "joe_seq": 0, "claude_read_seq": 0,
            "claude_working": 0, "seen_seq": 3, "info_seq": 0, "call_seq": 0}
    assert lifecycle.status({**base, "call_seq": 5}, False) == "review"
    assert lifecycle.status({**base, "info_seq": 5}, False) == "review"
    assert lifecycle.status({**base, "info_seq": 5, "call_seq": 6}, False) == "review"
    assert lifecycle.status({**base, "call_seq": 5}, True) == "question"
    for gone in ("info", "look"):
        assert gone not in lifecycle.STATUSES and gone not in lifecycle.SECTIONS


def test_waiting_install_round_trips_over_mcp_then_review_and_an_owner_reply_reopens_it(manager):
    ok, item = call(manager, "task_manager_add", {"list": "all", "text": "built, not installed"})
    ok, item = call(manager, "task_manager_update", {"item": item["id"], "state": "waiting", "waiting_on": "the staging restart", "wait_kind": "install"})
    assert ok and item["state"] == "waiting" and item["status"] == "waiting"
    assert item["section"] == "waiting"
    ok, listed = call(manager, "task_manager_tasks_list", {"list": "all"})
    assert [i["status"] for i in listed["items"] if i["id"] == item["id"]] == ["waiting"]
    ok, item = call(manager, "task_manager_update", {"item": item["id"], "state": "review"})
    assert item["status"] == "review"
    ok, item = call(manager, "task_manager_update", {"item": item["id"], "state": "waiting", "waiting_on": "Joe runs the staging restart", "wait_kind": "install"})
    reopened = huddle_store(manager).post(item["id"], "still broken", actor=JOE, kind="reply")["item"]
    assert reopened["state"] == "open" and reopened["status"] == "waiting_to_send"


def test_working_takes_a_waiting_install_item_back_to_working(manager):
    ok, item = call(manager, "task_manager_add", {"list": "all", "text": "again"})
    call(manager, "task_manager_update", {"item": item["id"], "state": "waiting", "waiting_on": "the staging restart", "wait_kind": "install"})
    ok, item = call(manager, "task_manager_update", {"item": item["id"], "state": "working"})
    assert item["state"] == "open" and item["status"] == "working"


def test_a_state_change_after_an_info_files_the_item_by_its_state_never_in_info(manager):
    store = huddle_store(manager)
    item = store.add("all", "info then state", actor=JOE)
    call(manager, "task_manager_update", {"item": item["id"], "state": "working"})
    store.post(item["id"], "progress", actor=CLAUDE, kind="info")

    def now():
        row = store.item(item["id"])
        return row["status"], row["section"], row["info_unread"]

    assert now() == ("working", "working", 1)
    call(manager, "task_manager_update", {"item": item["id"], "state": "waiting", "waiting_on": "the staging restart", "wait_kind": "install"})
    assert now() == ("waiting", "waiting", 1)
    call(manager, "task_manager_update", {"item": item["id"], "state": "review"})
    assert now() == ("review", "review", 1)
    store.post(item["id"], "one more fyi", actor=CLAUDE, kind="info")
    assert now() == ("review", "review", 2)
    call(manager, "task_manager_update", {"item": item["id"], "state": "open"})
    assert now()[1] == "open" and now()[2] == 2


def _nudge_line(manager, list_key: str) -> str:
    from src.cplugs.huddle.nudge_store import NudgeStore
    from src.cplugs.huddle.nudge import lines, planning, settings
    cands = [planning.Candidate(*t) for t in NudgeStore(huddle_store(manager)).candidates(list_key) if t[1] == lifecycle.WORKING]
    return lines.claimed_line(cands, max(c.last_activity for c in cands) + 3700, settings.read({}).texts, 5)


def test_the_nudge_says_the_agent_set_the_item_working(manager):
    ok, item = call(manager, "task_manager_add", {"list": "all", "text": "mine"})
    call(manager, "task_manager_update", {"item": item["id"], "state": "working"})
    assert '"mine" (working: you set it working)' in _nudge_line(manager, "all")


