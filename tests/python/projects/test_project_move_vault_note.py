
from __future__ import annotations

from contextlib import closing

from src.core.backup_health import vault_moves
from src.core.db import connect
from src.core.project_move.apply import apply_plan
from tests.python.projects.move_world import plan_for as _plan


def test_apply_notes_every_transcript_folder_it_renames(world):
    plan = _plan(world, move_folder=True)
    assert plan.transcript_moves
    with closing(connect(world.db, create=False)) as conn:
        apply_plan(conn, plan, state_dir=world.state)
    assert sorted(vault_moves.recent_folders(world.state)) == sorted(m["from"].rstrip("/") for m in plan.transcript_moves)
