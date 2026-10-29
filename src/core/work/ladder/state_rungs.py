
from __future__ import annotations

from src.core.work.ladder.feature_rungs import release_trigger_sql

DONE_MIGRATION = (
    release_trigger_sql("'done'", replace=True)
    + "UPDATE items SET state = 'done' WHERE state IN ('approved', 'approved_with_note');"
)

WAITING_MIGRATION = "UPDATE items SET state = 'waiting' WHERE state = 'waiting_install';"

TODO_MIGRATION = "UPDATE items SET state = 'todo' WHERE state = 'back_burner';"

REVIEW_MIGRATION = "UPDATE items SET state = 'review' WHERE state = 'done_by_claude';"

NUDGE_BASIS_MIGRATION = (
    "UPDATE item_nudges SET basis = 'done' || substr(basis, 9) WHERE substr(basis, 1, 9) = 'approved|';"
    "UPDATE item_nudges SET basis = 'done' || substr(basis, 19) WHERE substr(basis, 1, 19) = 'approved_with_note|';"
    "UPDATE item_nudges SET basis = 'waiting' || substr(basis, 16) WHERE substr(basis, 1, 16) = 'waiting_install|';"
    "UPDATE item_nudges SET basis = 'todo' || substr(basis, 12) WHERE substr(basis, 1, 12) = 'back_burner|';"
    "UPDATE item_nudges SET basis = 'review' || substr(basis, 15) WHERE substr(basis, 1, 15) = 'done_by_claude|';"
)

BACKUPS = {34: "pre-done", 35: "pre-waiting", 36: "pre-todo", 37: "pre-review"}
