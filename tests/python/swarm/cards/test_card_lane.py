
from __future__ import annotations

import asyncio
from typing import Any

import pytest
import structlog

from src.core.swarm.cards import effects, ops
from src.cplugs.huddle import lane
from src.cplugs.huddle.cards import driven
from src.cplugs.sdk.cards import CardRefused
# ruff: noqa: F401  (the imported names are pytest fixtures and shared helpers)
from tests.python.swarm.cards.test_card_enforcement import LIST, approved_rows, call, col, dealt_to, owner, sql_rows, world
from tests.python.swarm.cards.test_card_validation import card, child_caller, in_review, verdict, vw


def set_lane(w, card_id: int, lane: str) -> None:
    conn = w.huddle._connect(True)
    try:
        with conn:
            conn.execute("UPDATE work_items SET lane = ? WHERE id = ?", (lane, card_id))
    finally:
        conn.close()


def test_a_card_an_agent_made_is_swarm_lane_and_auto_done_ticks_it(vw):
    w = vw
    owner(ops.set_rules, None, list_key=LIST, changes={"auto_validate": True, "auto_done": True})
    cid = in_review(w)
    assert sql_rows(w, "SELECT lane FROM work_items WHERE id = ?", cid)[0]["lane"] == "swarm"
    out = verdict(w, child_caller(w), card_id=cid, verdict="pass", proof="all green")
    assert out["column"] == "done" and approved_rows(w)
    assert [r["by"] for r in sql_rows(w, "SELECT by FROM work_card_events WHERE kind = 'state' AND item_id = ? AND to_col = 'done'", cid)] == ["auto_done"]


def test_auto_done_never_ticks_a_task_manager_task_even_after_a_pass(vw):
    w = vw
    owner(ops.set_rules, None, list_key=LIST, changes={"auto_validate": True, "auto_done": True})
    cid = in_review(w)
    set_lane(w, cid, "task_manager")
    out = verdict(w, child_caller(w), card_id=cid, verdict="pass", proof="all green")
    assert out["column"] == "review" and out["mark"]["name"] == "validated" and not approved_rows(w)
    assert owner(ops.done, cid)["column"] == "done"


def test_the_swarm_never_deletes_a_task_manager_task_and_the_owner_does(vw):
    w = vw
    cid = in_review(w)
    set_lane(w, cid, "task_manager")
    with pytest.raises(CardRefused):
        asyncio.run(asyncio.to_thread(driven.delete, w.huddle, cid, {}, "agent:3"))
    assert sql_rows(w, "SELECT deleted FROM work_items WHERE id = ?", cid)[0]["deleted"] == 0
    owner(ops.delete, cid)
    assert sql_rows(w, "SELECT deleted FROM work_items WHERE id = ?", cid)[0]["deleted"] == 1


def test_auto_done_of_a_swarm_parent_leaves_a_task_manager_child_to_the_owner_and_finishes(vw):
    w = vw
    kid = in_review(w, slug="fixer", title="kid")
    parent = dealt_to(w, "builder", "parent")
    conn = w.huddle._connect(True)
    try:
        with conn:
            conn.execute("UPDATE work_items SET card_parent = ?, card_accepted_at = 1, lane = 'task_manager' WHERE id = ?", (parent, kid))
    finally:
        conn.close()
    call(w, "builder", "swarm_card_finish", needs_owner=True, owner_ask="check it", card_id=parent, result="done", how_to_validate="steps")
    out = asyncio.run(asyncio.to_thread(driven.done, w.huddle, parent, {}, "auto_done"))
    assert any(e["kind"] == "post" for e in out["effects"])
    states = {r["id"]: r["state"] for r in sql_rows(w, "SELECT id, state FROM work_items WHERE id IN (?, ?)", parent, kid)}
    assert states == {parent: "done", kid: "review"}


def _levels(logs, event: str):
    return [(e["log_level"], e.get("code")) for e in logs if e["event"] == event]


def test_an_auto_done_refused_by_the_lane_is_an_info_skip_not_a_warning(vw):
    w = vw
    owner(ops.set_rules, None, list_key=LIST, changes={"auto_done": True})
    cid = dealt_to(w, "fixer", "owner task")
    set_lane(w, cid, "task_manager")
    with structlog.testing.capture_logs() as logs:
        call(w, "fixer", "swarm_card_finish", needs_owner=True, owner_ask="check it", card_id=cid, result="done it", how_to_validate="steps")
    assert col(w, cid) == "review"
    assert _levels(logs, "swarm_card_effect_failed") == []
    assert _levels(logs, "swarm_card_auto_done_skipped") == [("info", "task_manager_lane")]

    owner(ops.set_rules, None, list_key=LIST, changes={"auto_validate": True})
    cid = in_review(w, slug="builder", title="validated owner task")
    set_lane(w, cid, "task_manager")
    with structlog.testing.capture_logs() as logs:
        verdict(w, child_caller(w), card_id=cid, verdict="pass", proof="all green")
    assert col(w, cid) == "review"
    assert _levels(logs, "swarm_card_auto_done_failed") == []
    assert ("info", "task_manager_lane") in _levels(logs, "swarm_card_auto_done_skipped")
    assert lane.REFUSED_CODE in effects.AUTO_DONE_SKIPS


def test_an_agent_made_card_is_born_by_that_agent_as_the_card_log_says(vw):
    w = vw
    made = call(w, "boss", "swarm_card_create", summary="a plain line", title="parent", project_id=16)["card"]
    boss = f"agent:{w.agents['boss']['id']}"
    assert [r["by"] for r in sql_rows(w, "SELECT by FROM work_card_events WHERE kind = 'state' AND item_id = ? AND detail = 'born'", made["id"])] == [boss]
    assert [r["by"] for r in sql_rows(w, "SELECT by FROM work_card_events WHERE item_id = ? AND kind = 'created'", made["id"])] == [boss]


def test_a_card_made_with_a_parent_links_the_parents_original_ask(vw):
    w = vw
    made = call(w, "boss", "swarm_card_create", summary="a plain line", title="parent", project_id=16)["card"]
    conn = w.huddle._connect(True)
    try:
        with conn:
            entry = conn.execute("INSERT INTO work_inbox (list_key, raw_text, author, created_at, status) VALUES ('16', 'make dark mode', 'joe', 1, "
                                 "'filed')").lastrowid
            conn.execute("UPDATE work_items SET inbox_id = ? WHERE id = ?", (entry, made["id"]))
    finally:
        conn.close()
    child = call(w, "boss", "swarm_card_create", summary="a part", title="child", project_id=16, parent=made["id"])["card"]
    assert sql_rows(w, "SELECT inbox_id FROM work_items WHERE id = ?", child["id"])[0]["inbox_id"] == entry
