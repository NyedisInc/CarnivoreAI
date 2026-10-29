
from __future__ import annotations

from src.core.schema_ledger.freeze import check_freeze, read_freeze
from src.core.schema_ledger.ledger import check_ledger, parse_ledger
from src.core.work import ladder
from tests.python.cplugs.huddle.task_manager_ledger import TASK_MANAGER_FREEZE, TASK_MANAGER_LEDGER


def test_huddle_ladder_is_frozen_at_the_marker() -> None:
    check_freeze("huddle", TASK_MANAGER_FREEZE, len(ladder.MIGRATIONS), "docs/maintenance-history.md, 'The huddle rung freeze'")


def test_marker_says_49() -> None:
    assert read_freeze(TASK_MANAGER_FREEZE) == 49


def test_huddle_ledger_matches_the_49_rungs() -> None:
    check_ledger(TASK_MANAGER_LEDGER)
    assert len(parse_ledger(TASK_MANAGER_LEDGER.path, "H")) == 49
