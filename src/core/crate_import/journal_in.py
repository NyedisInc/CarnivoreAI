
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Tuple

import structlog

from src.core.project_move.paths import PathMapping, rebase_journal_for

logger = structlog.get_logger()

JOURNAL_UPDATED = "updated"
JOURNAL_NOTHING = "nothing_to_change"
JOURNAL_UNREADABLE = "unreadable"
JOURNAL_FAILED = "failed"
JOURNAL_NOT_NEEDED = "not_needed"


@dataclass(frozen=True)
class JournalOutcome:

    state: str
    rewritten: int = 0

    def as_json(self) -> dict:
        return {"state": self.state, "rewritten": self.rewritten}


def mapping_moves(mapping: PathMapping) -> bool:
    return any(old != new for old, new in mapping.rules)


def rebase_for_import(state_dir: Path, mapping: PathMapping, session_uuids: Iterable[str]) -> JournalOutcome:
    """Rebase the journal entries of ``session_uuids`` through ``mapping``. Blocking (file I/O under the journal lock).

    Inputs: state_dir (the Carnivore state folder); mapping; session_uuids (the crate's sessions).
    Output: JournalOutcome; ``not_needed`` when the mapping moves nothing, ``unreadable`` when the journal could not be read (it is
    left exactly as it was), ``failed`` on an I/O error. Example: rebase_for_import(state, mapping, ["u"]).state -> 'updated'
    """
    from src.core.session_journal_task import mutate_journal

    if not mapping_moves(mapping):
        return JournalOutcome(JOURNAL_NOT_NEEDED)
    wanted = tuple(session_uuids)

    def change(journal: Any) -> Tuple[int, bool]:
        count = rebase_journal_for(journal, mapping, wanted)
        return count, count > 0

    try:
        count = mutate_journal(state_dir, change)
    except OSError as exc:
        logger.warning("crate_import_journal_failed", error=str(exc))
        return JournalOutcome(JOURNAL_FAILED)
    if count is None:
        return JournalOutcome(JOURNAL_UNREADABLE)
    return JournalOutcome(JOURNAL_UPDATED if count else JOURNAL_NOTHING, int(count))
