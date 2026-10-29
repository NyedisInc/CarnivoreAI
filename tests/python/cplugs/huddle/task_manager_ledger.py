
from __future__ import annotations

from typing import List

from src.core.schema_ledger.ledger import DATA_DIR, LadderSpec, Rung, sql_rungs
from src.core.work import ladder

TASK_MANAGER_FREEZE = DATA_DIR / "huddle.freeze"


def _rungs() -> List[Rung]:
    return sql_rungs(ladder.MIGRATIONS)


TASK_MANAGER_LEDGER = LadderSpec("huddle", "H", DATA_DIR / "huddle.ledger", _rungs)
