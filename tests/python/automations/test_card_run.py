from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict

import src.config  # noqa: F401
from src.core.automations import models as m
from src.core.automations.scheduler import Context
from src.core.automations.targets import card
from tests.python.swarm.cards.test_card_board_actions import on_board
from tests.python.swarm.cards.test_card_enforcement import sql_rows, world  # noqa: F401

# ruff: noqa: F811


def target(**extra: Any) -> Dict[str, Any]:
    return {"kind": "swarm_card", "project_id": 16, "title": "weekly audit {date}", "summary": "look at the week", "text": "", "how_to_validate": "", "queued": False, **extra}


def run(w, **extra: Any) -> m.RunOutcome:
    automation = {"automation_id": "a1", "name": "audit", "target": target(**extra), "delivery": {"notify": False, "notify_on": None}}
    return asyncio.run(card.run(Context(w.state, SimpleNamespace(), "boot"), automation, {"run_id": "r1"}))


def cards() -> int:
    return len(on_board())


def test_card_runs(world):
    assert cards() == 0
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    first = run(world)
    assert first.status == m.SUCCEEDED and first.report["column"] == "todo"
    made = on_board()[first.report["card_id"]]
    assert cards() == 1 and made["column"] == "todo" and not made["queued"] and made["title"] == f"weekly audit {today}"
    second = run(world, queued=True)
    assert second.status == m.SUCCEEDED and on_board()[second.report["card_id"]]["column"] == "in_progress" and cards() == 2
    assert card.expand("{week}", datetime(2026, 10, 9)) == "2026-W41"
    before = cards()
    over = run(world, title="x" * 121)
    assert (over.status, over.reason) == (m.FAILED, "target_invalid") and cards() == before
    exact = run(world, title="{date} " + "y" * (120 - len(today) - 1))
    assert exact.status == m.SUCCEEDED and cards() == before + 1
    assert card.validate_target(target()) is None
    assert card.validate_target(target(project_id=999)) == "project_missing"
    assert sql_rows(world, "SELECT COUNT(*) FROM work_items")[0][0] >= 3
