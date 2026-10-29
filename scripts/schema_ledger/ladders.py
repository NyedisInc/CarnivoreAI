
from __future__ import annotations

from typing import Dict, List

from src.core.schema_ledger.ledger import DATA_DIR, LadderSpec, Rung, sql_rungs, step_rungs


def _core_rungs() -> List[Rung]:
    from src.core import db_steps

    return step_rungs(db_steps.STEPS)


def _huddle_rungs() -> List[Rung]:
    from src.core.work import ladder

    return sql_rungs(ladder.MIGRATIONS)


def _work_rungs() -> List[Rung]:
    from src.core.work import work_ladder

    return sql_rungs(work_ladder.MIGRATIONS, ["task-manager-tables-in-carnivore-db", "work-held-tells-becomes-work-held-sends", "work-items-review-checks"])


LADDERS: Dict[str, LadderSpec] = {
    "core": LadderSpec("core", "C", DATA_DIR / "core.ledger", _core_rungs),
    "huddle": LadderSpec("huddle", "H", DATA_DIR / "huddle.ledger", _huddle_rungs),
    "work": LadderSpec("work", "W", DATA_DIR / "work.ledger", _work_rungs),
}
