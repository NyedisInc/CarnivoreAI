
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from src.cplugs.huddle import swarm_port, rules
from src.cplugs.huddle.answer_writer import AnswerWriter
from src.cplugs.huddle.cards import flow, policy, reads, tx
from src.cplugs.huddle.cards.flow import CardAct
from src.cplugs.huddle.rules import CLAUDE, JOE, TaskManagerForbidden
from src.cplugs.huddle.store import TaskManagerStore
from src.core.work.storage import WorkStorage
from src.cplugs.sdk.swarm import SwarmError


@pytest.fixture()
def store(tmp_path: Path) -> TaskManagerStore:
    policy.drain_kicks()
    return TaskManagerStore(WorkStorage(tmp_path / "huddle"), notify=lambda key: None)


def sql(store: TaskManagerStore, query: str, *args: Any) -> List[sqlite3.Row]:
    with closing(store._connect(True)) as conn, conn:
        return conn.execute(query, args).fetchall()


def events(store: TaskManagerStore, item: int) -> List[tuple]:
    return [tuple(r) for r in sql(store, "SELECT kind, from_col, to_col, by, detail FROM work_card_events WHERE item_id = ? AND kind != 'state' ORDER BY id", item)]


def hold(store: TaskManagerStore, item: int, agent: int = 4) -> None:
    sql(store, "UPDATE work_items SET card_holder = ?, card_held_since = 5.0 WHERE id = ?", agent, item)


def test_an_add_logs_created_and_asks_one_deal_only_for_a_project_queue_card(store: TaskManagerStore):
    plain = store.add("12", "build it", actor=JOE)["id"]
    store.add("12", "and this", actor=JOE)
    shared = store.add("all", "shared one", actor=JOE)["id"]
    question = store.add("12", "which?", actor=CLAUDE, kind="question")["id"]
    swarm = store.add("12", "trust", actor=CLAUDE, created_key="swarm", swarm_ref="trust:4:ab")["id"]
    assert events(store, plain) == [("created", "", "todo", "owner", "")]
    assert events(store, shared) == [("created", "", "todo", "owner", "")]
    assert events(store, question) == events(store, swarm) == []
    deals = [tuple(r) for r in sql(store, "SELECT project_key, state, reasons FROM work_card_deals")]
    assert deals == [("12", "waiting", '["card_created"]')]
    assert policy.drain_kicks() == {"12"} and policy.drain_kicks() == set()


def test_a_held_card_refuses_a_plain_claude_state_change_a_claim_and_a_kind_change_but_not_its_text(store: TaskManagerStore):
    item = store.add("12", "held work", actor=JOE)["id"]
    hold(store, item)
    with pytest.raises(TaskManagerForbidden, match="held by a swarm agent"):
        store.update(item, actor=CLAUDE, state=rules.REVIEW)
    with pytest.raises(TaskManagerForbidden, match="held by a swarm agent"):
        store.mark_working(item, "sessB")
    authored = store.add("12", "claude's own held card", actor=CLAUDE)["id"]
    hold(store, authored)
    with pytest.raises(TaskManagerForbidden, match="held by a swarm agent"):
        store.update(authored, actor=CLAUDE, kind="waiting")
    assert store.update(item, actor=CLAUDE, title="a title")["title"] == "a title"
    assert [r["card_holder"] for r in sql(store, "SELECT card_holder FROM work_items WHERE id = ?", item)] == [4]


def test_a_finish_act_moves_to_review_gives_up_the_lease_and_an_owner_reply_sends_it_back_then_done_is_the_win(store: TaskManagerStore):
    item = store.add("12", "held work", actor=JOE)["id"]
    hold(store, item)
    store.update(item, actor=CLAUDE, state=rules.REVIEW, act=CardAct("finish", "agent:4"))
    row = sql(store, "SELECT card_holder, card_last_holder, card_held_since FROM work_items WHERE id = ?", item)[0]
    assert tuple(row) == (None, 4, None)
    assert events(store, item)[-1] == ("finished", "in_progress", "review", "agent:4", "")
    store.post(item, "not quite, redo it", actor=JOE)
    store.post(item, "redone", actor=CLAUDE, kind="answer", quote_text="not quite, redo it")
    assert events(store, item)[-1] == ("sent_back", "review", "in_progress", "owner", "reply")
    assert [tuple(r) for r in sql(store, "SELECT state, reasons FROM work_card_deals WHERE project_key = '12'")] == [("waiting", '["card_created", "agent_freed", "sent_back"]')]
    store.update(item, actor=CLAUDE, state=rules.REVIEW)
    store.update(item, actor=JOE, approve=True)
    assert events(store, item)[-2:] == [("moved", "in_progress", "review", "claude", ""), ("done", "review", "done", "owner", "")]
    with closing(store._connect(False)) as conn:
        assert reads.wins(conn, ["12"], 0.0) == {"through_review_today": 1, "in_review": 0}
        assert reads.wins(conn, ["12"], 9e12)["through_review_today"] == 0
        assert reads.wins(conn, [], 0.0) == {"through_review_today": 0, "in_review": 0}


def test_a_delete_drops_the_lease_and_a_move_returns_a_held_card_to_todo_of_the_new_list(store: TaskManagerStore):
    gone, moved = store.add("12", "to delete", actor=JOE)["id"], store.add("12", "to move", actor=JOE)["id"]
    for item in (gone, moved):
        hold(store, item)
    sql(store, "UPDATE work_items SET card_pin_agent = 4, card_dealt_to = 4, card_parent = 99 WHERE id = ?", moved)
    store.delete(gone, actor=JOE)
    assert events(store, gone)[-1] == ("deleted", "in_progress", "", "owner", "")
    assert tuple(sql(store, "SELECT card_holder, card_last_holder, deleted FROM work_items WHERE id = ?", gone)[0]) == (None, 4, 1)
    store.move(moved, "13", actor=JOE)
    row = sql(store, "SELECT list_key, card_holder, card_last_holder, card_pin_agent, card_dealt_to, card_parent FROM work_items WHERE id = ?", moved)[0]
    assert tuple(row) == ("13", None, 4, None, None, 99)
    assert events(store, moved)[-1] == ("moved", "in_progress", "todo", "owner", "list 12 to 13")
    assert [r["project_key"] for r in sql(store, "SELECT project_key FROM work_card_deals ORDER BY project_key")] == ["12", "13"]


def test_a_form_answer_that_reopens_a_review_card_logs_sent_back_and_asks_for_a_deal(store: TaskManagerStore):
    item = store.add("12", "held work", actor=JOE)["id"]
    question = store.post(item, "which way?", actor=CLAUDE, kind="question")["message"]["id"]
    store.update(item, actor=JOE, state=rules.REVIEW)
    sql(store, "DELETE FROM work_card_deals")
    AnswerWriter(store).submit(question, {})
    assert events(store, item)[-1] == ("sent_back", "review", "in_progress", "owner", "reply")
    assert [tuple(r) for r in sql(store, "SELECT state, reasons FROM work_card_deals WHERE project_key = '12'")] == [("waiting", '["sent_back"]')]


def test_a_plain_claude_move_of_a_held_card_is_refused_and_the_owner_may(store: TaskManagerStore):
    held_item, free = store.add("12", "held", actor=JOE)["id"], store.add("12", "free", actor=JOE)["id"]
    hold(store, held_item)
    with pytest.raises(TaskManagerForbidden, match="held by a swarm agent"):
        store.move(held_item, "13", actor=CLAUDE)
    with pytest.raises(TaskManagerForbidden, match="only joe deletes"):
        store.delete(held_item, actor=CLAUDE)
    assert [tuple(r) for r in sql(store, "SELECT list_key, card_holder, deleted FROM work_items WHERE id = ?", held_item)] == [("12", 4, 0)]
    store.move(free, "13", actor=CLAUDE)
    store.delete(held_item, actor=JOE)


def test_a_legacy_claim_is_in_progress_without_a_lease_and_a_fork_logs_both_sides(store: TaskManagerStore):
    item = store.add("12", "claimed work", actor=JOE)["id"]
    store.mark_working(item, "sessA")
    with closing(store._connect(False)) as conn:
        card = reads.one(conn, item)
    assert (card["column"], card["holder"], card["legacy_claim"]) == ("in_progress", None, "sessA")
    pair = store.fork(item, actor=JOE, fork_state="done")
    assert events(store, pair["fork"]["id"]) == [("created", "", "todo", "owner", ""), ("done", "todo", "done", "owner", "")]


def test_the_swarm_port_never_approves_or_tombstones_a_card(store: TaskManagerStore, tmp_path: Path):
    card = store.add("agent:3", "a company parent card", actor=JOE)["id"]
    sql(store, "UPDATE work_items SET card_last_holder = 4 WHERE id = ?", card)
    plain = store.add("agent:3", "a plain task nobody dealt", actor=JOE)["id"]
    notice = store.add("agent:3", "naming", actor=CLAUDE, created_key="swarm", swarm_ref="naming:2")["id"]
    ctx = SimpleNamespace(storage=store._storage, settings={}, swarm=None, notify=lambda *a, **k: None)
    port = swarm_port.TaskManagerSwarmPort(ctx)
    with pytest.raises(SwarmError, match="swarm card"):
        asyncio.run(port.close_card(card, "done"))
    asyncio.run(port.close_card(notice, "done"))
    asyncio.run(port.archive_thread("agent:3"))
    live: Dict[int, str] = {i["id"]: i["state"] for i in store.list_items("agent:3")["items"]}
    assert live == {card: "open"}
    assert plain not in live


def test_a_teardown_of_a_thread_with_only_plain_items_leaves_no_list_behind(store: TaskManagerStore):
    store.add("agent:5", "plain one", actor=JOE)
    store.add("agent:5", "plain two", actor=JOE)
    ctx = SimpleNamespace(storage=store._storage, settings={}, swarm=None, notify=lambda *a, **k: None)
    asyncio.run(swarm_port.TaskManagerSwarmPort(ctx).archive_thread("agent:5"))
    assert store.list_items("agent:5")["items"] == []
    row = store.summary()["lists"].get("agent:5", {})
    assert (row.get("items", 0), row.get("needs_you", 0), row.get("incomplete", 0)) == (0, 0, 0)


def test_tx_write_notifies_each_touched_list_after_the_commit_and_nothing_on_a_rollback(store: TaskManagerStore):
    told: List[str] = []
    store._notify = told.append
    keys = {"12", "all"}
    with tx.write(store, keys) as conn:
        conn.execute("INSERT INTO work_meta VALUES ('probe', 1)")
        assert told == []
    assert told == ["12", "all"]
    told.clear()
    with pytest.raises(RuntimeError):
        with tx.write(store, {"12"}) as conn:
            conn.execute("INSERT INTO work_meta VALUES ('probe2', 1)")
            raise RuntimeError("boom")
    assert told == [] and not sql(store, "SELECT 1 FROM work_meta WHERE k = 'probe2'")
    item = store.add("12", "bumped", actor=JOE)["id"]
    before = sql(store, "SELECT seq, revision FROM work_items WHERE id = ?", item)[0]
    with tx.write(store, set()) as conn:
        assert tx.bump(conn, item, CLAUDE) > before["seq"]
    after = sql(store, "SELECT seq, revision, attention_seq FROM work_items WHERE id = ?", item)[0]
    assert (after["revision"], after["attention_seq"] == after["seq"]) == (before["revision"] + 1, True)


def test_an_unknown_event_kind_is_refused(store: TaskManagerStore):
    with closing(store._connect(True)) as conn, conn:
        with pytest.raises(ValueError, match="unknown card event kind"):
            flow._event(conn, 1, "teleported", list_key="12", by="owner", now=1.0)
