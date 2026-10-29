
from __future__ import annotations

from typing import Tuple

RENAME_RUNGS: Tuple[Tuple[int, str, Tuple[Tuple[str, str], ...]], ...] = (
    (34, "pre-done", (("approved", "done"), ("approved_with_note", "done"))),
    (35, "pre-waiting", (("waiting_install", "waiting"),)),
    (36, "pre-todo", (("back_burner", "todo"),)),
    (37, "pre-review", (("done_by_claude", "review"),)),
)

RENAMES: Tuple[Tuple[str, str], ...] = tuple(pair for _, _, pairs in RENAME_RUNGS for pair in pairs)
