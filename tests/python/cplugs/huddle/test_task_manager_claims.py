
from __future__ import annotations

import asyncio
from contextlib import closing
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.core.mcp.caller import AgentCaller
from src.core.work.work_ladder import VERSION as WORK_VERSION
from src.cplugs.huddle import conversation_release
from src.cplugs.huddle.rules import CLAUDE, JOE
from src.cplugs.sdk import conversation_events
from tests.python.cplugs.huddle.test_task_manager_lifecycle import status, tell
from tests.python.cplugs.huddle.test_task_manager_mcp import call, huddle_store, manager  # noqa: F401


def claimed(manager) -> int:  # noqa: F811
    item = huddle_store(manager).add("12", "do the thing", actor=JOE)
    ok, updated = call(manager, "task_manager_update", {"item": item["id"], "state": "working"})
    assert ok and updated["status"] == "working"
    return item["id"]


def claimant(manager, item: int) -> str:  # noqa: F811
    with closing(huddle_store(manager)._connect(False)) as conn:
        return conn.execute("SELECT claude_working_by FROM work_items WHERE id = ?", (item,)).fetchone()[0]


def test_the_claim_names_its_claimant_and_nothing_sweeps_it(manager):
    item = claimed(manager)
    assert claimant(manager, item) == "ses_1"
    assert status(manager, item) == "working"


def test_working_survives_a_restart_of_the_store(manager):
    item = claimed(manager)
    reopened = huddle_store(manager)
    assert reopened.item(item)["status"] == "working"


def test_a_caller_with_no_session_still_makes_it_working(manager):
    item = huddle_store(manager).add("all", "fix it", actor=JOE)
    assert huddle_store(manager).mark_working(item["id"], None)["status"] == "working"


def test_an_info_post_keeps_working(manager):
    item = claimed(manager)
    assert call(manager, "task_manager_reply", {"item": item, "text": "halfway", "kind": "info"})[0]
    assert status(manager, item) == "working" and claimant(manager, item) == "ses_1"


def test_a_reply_with_no_kind_while_working_is_info_and_keeps_it(manager):
    item = claimed(manager)
    assert call(manager, "task_manager_reply", {"item": item, "text": "still on it"})[0]
    assert status(manager, item) == "working"


def test_the_owners_reply_does_not_end_it_and_shows_waiting_then_working_again(manager):
    item = claimed(manager)
    huddle_store(manager).post(item, "also this", actor=JOE, kind="reply")
    assert status(manager, item) == "waiting_to_send"
    assert claimant(manager, item) == "ses_1"
    tell(manager, "12")
    call(manager, "task_manager_tasks_list", {"list": "12"})
    assert status(manager, item) == "working"


def test_the_owners_edit_of_an_open_working_item_does_not_end_it(manager):
    item = claimed(manager)
    huddle_store(manager).update(item, actor=JOE, text="reworded")
    assert claimant(manager, item) == "ses_1"


def test_a_claude_question_ends_it(manager):
    item = claimed(manager)
    assert call(manager, "task_manager_ask", {"item": item, "text": "which one?"})[0]
    assert claimant(manager, item) == ""
    huddle_store(manager).mark_answered(item, actor=JOE)
    assert status(manager, item) == "open"


def test_an_old_look_in_the_store_ends_it_and_a_notify_info_keeps_it(manager):
    item = claimed(manager)
    assert call(manager, "task_manager_reply", {"item": item, "text": "come see", "kind": "attention"})[0]
    assert status(manager, item) == "working" and claimant(manager, item) != ""
    huddle_store(manager).post(item, "old look", actor="claude", kind="attention")
    assert status(manager, item) != "working" and claimant(manager, item) == ""


@pytest.mark.parametrize("state", ["review", "waiting", "todo"])
def test_a_state_change_ends_it(manager, state):
    item = claimed(manager)
    park = {"waiting_on": "the staging restart", "wait_kind": "install"} if state == "waiting" else {}
    assert call(manager, "task_manager_update", {"item": item, "state": state, **park})[0]
    assert claimant(manager, item) == "" and status(manager, item) != "working"


def test_claude_setting_open_explicitly_ends_it(manager):
    item = claimed(manager)
    assert call(manager, "task_manager_update", {"item": item, "state": "open"})[0]
    assert status(manager, item) == "open" and claimant(manager, item) == ""


def test_a_text_only_update_by_claude_keeps_it(manager):
    item = huddle_store(manager).add("12", "mine", actor=CLAUDE)["id"]
    assert call(manager, "task_manager_update", {"item": item, "state": "working"})[0]
    assert call(manager, "task_manager_update", {"item": item, "text": "mine, reworded"})[0]
    assert status(manager, item) == "working"


def test_the_owners_tick_ends_it(manager):
    item = claimed(manager)
    huddle_store(manager).update(item, actor=JOE, approve=True)
    assert claimant(manager, item) == ""


def test_the_owners_delete_takes_it_out_of_working(manager):
    item = claimed(manager)
    huddle_store(manager).delete(item, actor=JOE)
    ok, listed = call(manager, "task_manager_tasks_list", {"list": "12"})
    assert ok and [i for i in listed["items"] if i["status"] == "working"] == []


def with_second_session(manager) -> AgentCaller:
    first = asyncio.run(manager.list_session_infos())[0]
    second = SimpleNamespace(tmux_session=None, label=None, session=SimpleNamespace(id="ses_2"), project_id=99, host_key="local")

    async def infos():
        return [first, second]

    manager.list_session_infos = infos
    return AgentCaller("ses_2", "cloude_b", "ses_2")


def test_a_read_by_another_session_of_a_replied_and_told_item_does_not_claim_it(manager):
    other = with_second_session(manager)
    store = huddle_store(manager)
    item = store.add("all", "fix it", actor=JOE)
    store.post(item["id"], "also handle the edge", actor=JOE, kind="reply")
    tell(manager, "all")
    ok, listed = call(manager, "task_manager_tasks_list", {"list": "all"}, caller=other)
    assert ok and [i["status"] for i in listed["items"]] == ["open"]
    assert claimant(manager, item["id"]) == "" and status(manager, item["id"]) == "open"
    call(manager, "task_manager_changes", {"since": 0})
    assert claimant(manager, item["id"]) == "" and status(manager, item["id"]) == "open"


def test_a_read_never_moves_an_existing_claim(manager):
    item = claimed(manager)
    other = with_second_session(manager)
    huddle_store(manager).post(item, "also this", actor=JOE, kind="reply")
    tell(manager, "12")
    call(manager, "task_manager_tasks_list", {"list": "12"}, caller=other)
    assert claimant(manager, item) == "ses_1"


def test_a_read_with_no_tell_claims_nothing(manager):
    item = huddle_store(manager).add("all", "fix it", actor=JOE)
    call(manager, "task_manager_tasks_list", {"list": "all"})
    assert claimant(manager, item["id"]) == "" and status(manager, item["id"]) == "open"


def test_a_conversation_change_ends_every_claim_the_session_held_and_only_its(manager):
    store = huddle_store(manager)
    mine, also, theirs = (store.add("12", t, actor=JOE)["id"] for t in ("a", "b", "c"))
    store.mark_working(mine, "key-a")
    store.mark_working(also, "key-a")
    store.mark_working(theirs, "key-b")
    assert store.release_conversation_claims("key-a") == ["12"]
    assert (claimant(manager, mine), claimant(manager, also), claimant(manager, theirs)) == ("", "", "key-b")
    assert status(manager, mine) == "open" and status(manager, theirs) == "working"
    assert store.release_conversation_claims("") == [] and store.release_conversation_claims("nobody") == []


def test_the_host_event_releases_the_claims_of_the_changed_session(manager, monkeypatch):
    store = huddle_store(manager)
    item = store.add("12", "a", actor=JOE)["id"]
    store.mark_working(item, "key-a")
    monkeypatch.setattr(conversation_release.service, "store", lambda ctx: store)

    async def run() -> None:
        conversation_release.start(SimpleNamespace())
        try:
            conversation_events.publish_changed("key-a")
            await asyncio.sleep(0)
            await asyncio.gather(*list(conversation_release._pending))
        finally:
            conversation_release.stop()

    asyncio.run(run())
    assert claimant(manager, item) == ""
    store.mark_working(item, "key-a")
    conversation_events.publish_changed("key-a")
    assert claimant(manager, item) == "key-a"


def _seed_claim(conn, item_id: int, holder: str, ops: list) -> None:
    conn.execute("INSERT INTO work_items (id, list_key, text, state, created_by, created_at, updated_at, created_seq, seq, position, claude_working, claude_working_by, owner_session_key, joe_seq) "
                 "VALUES (?, '12', 't', 'open', 'joe', 1.0, 1.0, 1, 1, 0, 1, ?, ?, 1)", (item_id, holder, holder))
    for op, key in ops:
        conn.execute("INSERT INTO work_write_actors (item_id, op, actor_key, at) VALUES (?, ?, ?, 1.0)", (item_id, op, key))


def test_the_start_sweep_clears_only_the_claims_a_read_made_and_is_idempotent(manager):
    store = huddle_store(manager)
    with closing(store._connect(True)) as conn, conn:
        _seed_claim(conn, 901, "k1", [("pickup", "k1"), ("reply", "k1")])
        _seed_claim(conn, 902, "k1", [("pickup", "k1"), ("update", "k1")])
        _seed_claim(conn, 903, "k1", [("update", "k1"), ("ask", "k1"), ("pickup", "k1")])
        _seed_claim(conn, 904, "k1", [("update", "k1")])
        _seed_claim(conn, 905, "k1", [])
        _seed_claim(conn, 906, "k2", [("pickup", "k1"), ("update", "k2")])
        version = conn.execute("SELECT v FROM work_meta WHERE k = 'work_ladder'").fetchone()[0]
    assert store.sweep_read_claims() == [901, 903]
    assert store.sweep_read_claims() == []
    with closing(store._connect(False)) as conn:
        rows = {r[0]: r[1:] for r in conn.execute("SELECT id, claude_working, claude_working_by, owner_session_key FROM work_items WHERE id >= 901")}
        assert conn.execute("SELECT v FROM work_meta WHERE k = 'work_ladder'").fetchone()[0] == version == WORK_VERSION
        assert conn.execute("SELECT COUNT(*) FROM work_write_actors WHERE op = 'pickup'").fetchone()[0] == 4
    assert rows == {901: (0, "", ""), 902: (1, "k1", "k1"), 903: (0, "", ""), 904: (1, "k1", "k1"), 905: (1, "k1", "k1"), 906: (1, "k2", "k2")}


def _seed_owned(conn, item_id: int, owner: str, ops: list, *, claimed: bool = False, tagged: str = "") -> None:
    conn.execute("INSERT INTO work_items (id, list_key, text, state, created_by, created_at, updated_at, created_seq, seq, position, claude_working, claude_working_by, owner_session_key, tagged_session_key, joe_seq) "
                 "VALUES (?, '12', 't', 'open', 'joe', 1.0, 1.0, 1, 1, 0, ?, ?, ?, ?, 1)", (item_id, int(claimed), owner if claimed else "", owner, tagged))
    for op, key in ops:
        conn.execute("INSERT INTO work_write_actors (item_id, op, actor_key, at) VALUES (?, ?, ?, 1.0)", (item_id, op, key))


def test_the_start_sweep_clears_an_owner_only_a_read_pickup_set_and_is_idempotent(manager):
    store = huddle_store(manager)
    with closing(store._connect(True)) as conn, conn:
        _seed_owned(conn, 911, "k1", [("pickup", "k1")], tagged="t1")
        _seed_owned(conn, 912, "k1", [("pickup", "k1"), ("reply", "k1")])
        _seed_owned(conn, 913, "k1", [("update", "k1"), ("pickup", "k1")])
        _seed_owned(conn, 914, "k1", [("pickup", "k1")], claimed=True)
        _seed_owned(conn, 915, "k1", [("pickup", "k2")])
        _seed_owned(conn, 916, "k1", [])
        _seed_owned(conn, 917, "k1", [("pickup", "k1"), ("pickup", "k1")])
        version = conn.execute("SELECT v FROM work_meta WHERE k = 'work_ladder'").fetchone()[0]
    assert store.sweep_read_owners() == [911, 917]
    assert store.sweep_read_owners() == []
    with closing(store._connect(False)) as conn:
        rows = {r[0]: r[1:] for r in conn.execute("SELECT id, owner_session_key, tagged_session_key FROM work_items WHERE id >= 911")}
        assert conn.execute("SELECT v FROM work_meta WHERE k = 'work_ladder'").fetchone()[0] == version == WORK_VERSION
        assert conn.execute("SELECT COUNT(*) FROM work_write_actors WHERE op = 'pickup'").fetchone()[0] == 7
    assert rows == {911: ("", "t1"), 912: ("k1", ""), 913: ("k1", ""), 914: ("k1", ""), 915: ("k1", ""), 916: ("k1", ""), 917: ("", "")}


def test_the_watchers_done_edge_publishes_the_turn_end(monkeypatch):
    from src.core.attention import side_effects

    seen = []
    monkeypatch.setattr(side_effects.turn_events, "publish_turn_end", seen.append)
    effects = side_effects.AttentionSideEffects.__new__(side_effects.AttentionSideEffects)
    monkeypatch.setattr(effects, "withdraw_answered_ask", lambda target, transition: None)
    monkeypatch.setattr(effects, "_auto_ack", lambda *args: None)
    effects.on_done_edge(SimpleNamespace(session_id="ses_9", key="cloude_nine@1"), SimpleNamespace(at=datetime.now(timezone.utc)))
    assert seen == ["ses_9"]
