
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List, Tuple

import pytest

from src.core.work.storage import WorkStorage
from src.plugins.taskmanager import service
from src.plugins.taskmanager.cards import moves
from src.plugins.taskmanager.cards.port import TaskManagerCardPort
from src.plugins.taskmanager.rules import JOE


class Rig:

    def __init__(self, folder: Path) -> None:
        self.heard: List[Tuple[int, str, str]] = []
        self.reasons: List[str] = []
        swarm = SimpleNamespace(thread_changed=lambda key: None, deal_requested=lambda key: None,
                                card_moved=lambda card_id, before, after, reason: (self.heard.append((card_id, before, after)), self.reasons.append(reason)))
        self.ctx = SimpleNamespace(storage=WorkStorage(folder), settings={"view": "area"}, swarm=swarm, notify=lambda *a, **k: None, has=lambda perm: True)
        self.port = TaskManagerCardPort(self.ctx)

    def card(self, origin: str) -> int:
        made = asyncio.run(self.port.act("create", None, {"list_key": "12", "title": "A Story", "origin": origin}, "owner"))
        return int(made["card"]["id"])

    def act(self, op: str, card_id: int, **args: Any) -> None:
        asyncio.run(self.port.act(op, card_id, args, "owner"))


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    moves.drain()
    return Rig(tmp_path)


def test_the_task_managers_own_tick_of_an_argent_card_reports_it_done(rig: Rig) -> None:
    card = rig.card("argent:github:wi_1")
    service.store(rig.ctx).update(card, actor=JOE, approve=True)
    assert rig.heard == [(card, "todo", "done")]


def test_a_lane_move_a_board_drag_and_a_return_report_only_the_entries(rig: Rig) -> None:
    card = rig.card("argent:github:wi_1")
    rig.act("set_lane", card, queued=True)
    assert rig.heard == [(card, "todo", "in_progress")]
    rig.act("set_lane", card, queued=False)
    rig.act("set_lane", card, queued=True)
    rig.act("set_column", card, column="done")
    assert rig.heard == [(card, "todo", "in_progress"), (card, "todo", "in_progress"), (card, "in_progress", "done")]
    rig.act("set_column", card, column="todo")
    assert len(rig.heard) == 3


def test_a_tracker_driven_move_and_a_plain_card_report_nothing(rig: Rig) -> None:
    card, plain = rig.card("argent:github:wi_1"), rig.card("owner")
    rig.act("set_lane", card, queued=True, from_tracker=True)
    rig.act("set_column", card, column="done", from_tracker=True)
    rig.act("set_lane", plain, queued=True)
    rig.act("set_column", plain, column="done")
    assert rig.heard == []


def test_a_closing_agents_reason_rides_with_the_move(rig: Rig) -> None:
    card = rig.card("argent:jira:wi_9")
    rig.act("set_column", card, column="review")
    asyncio.run(rig.port.act("done", card, {"reason": "all validated"}, "owner"))
    assert rig.heard == [(card, "review", "done")] and rig.reasons == ["all validated"]


def _argent_in_review(rig: Rig) -> int:
    card = rig.card("argent:github:wi_1")
    rig.act("set_column", card, column="review")
    return card


def test_review_to_done_reports_once(rig: Rig) -> None:
    card = _argent_in_review(rig)
    rig.act("done", card)
    assert rig.heard == [(card, "review", "done")]


def test_a_tracker_driven_review_to_done_reports_nothing(rig: Rig) -> None:
    card = _argent_in_review(rig)
    rig.act("set_column", card, column="done", from_tracker=True)
    assert rig.heard == []


def test_a_queue_reports_the_entry(rig: Rig) -> None:
    card = rig.card("argent:github:wi_1")
    rig.act("queue", card)
    assert rig.heard == [(card, "todo", "in_progress")]


def test_an_auto_promote_reports_the_entry(rig: Rig) -> None:
    card = rig.card("argent:github:wi_1")
    rig.act("auto_promote", card, on=True)
    assert rig.heard == []
    asyncio.run(rig.port.act("promote", card, {}, "server"))
    assert rig.heard == [(card, "todo", "in_progress")]


def test_the_owners_deal_of_a_todo_card_reports_the_entry_once(rig: Rig) -> None:
    card = rig.card("argent:github:wi_1")
    rig.act("deal", card, agent_id=7, slot_ok=True)
    assert rig.heard == [(card, "todo", "in_progress")]


def test_a_card_that_waited_for_a_slot_reports_when_the_slot_frees(rig: Rig) -> None:
    card = rig.card("argent:github:wi_1")
    rig.act("deal", card, agent_id=7, slot_ok=False)
    assert rig.heard == []
    rig.act("complete_slot", card)
    assert rig.heard == [(card, "todo", "in_progress")]


def test_an_accepted_child_of_an_epic_reports_done(rig: Rig) -> None:
    epic = rig.card("owner")
    child = int(asyncio.run(rig.port.act("create", None, {"list_key": "12", "title": "A Story", "origin": "argent:github:wi_2", "parent": epic}, "owner"))["card"]["id"])
    rig.act("set_column", child, column="review")
    rig.act("accept_child", child, by_agent=7, report_id=1)
    assert rig.heard == [(child, "review", "done")]


def test_a_plain_sessions_working_claim_reports_the_entry(rig: Rig) -> None:
    card = rig.card("argent:github:wi_1")
    service.store(rig.ctx).mark_working(card, "session-a")
    assert rig.heard == [(card, "todo", "in_progress")]
