
from __future__ import annotations

import os
from contextlib import closing

from src.core.claude_transcript_correlate import slugify_project_dir as enc
from src.core.db import connect
from src.core.project_move.apply import apply_plan
from tests.python.projects.move_world import plan_for, snapshot


def _rows(w):
    return snapshot(w)[0]


def test_the_reverse_call_puts_the_move_back(world):
    rows_before = _rows(world)
    target = world.base / "org" / "initech" / "alpha"
    forward = plan_for(world, move_folder=True, new_root=str(target), create_parents=True)
    with closing(connect(world.db, create=False)) as conn:
        done = apply_plan(conn, forward, state_dir=world.state)
    reverse = done["reverse"]
    assert reverse == {**reverse, "project": world.ids["alpha"], "new_root": str(world.old),
                       "move_folder": True, "create_parents": False}
    assert "stays merged" in reverse["note"] and str(world.base / "org" / "initech") in reverse["note"]
    back = plan_for(world, move_folder=reverse["move_folder"], new_root=reverse["new_root"])
    assert back.ok, back.failed()
    with closing(connect(world.db, create=False)) as conn:
        apply_plan(conn, back, state_dir=world.state)
    assert _rows(world) == rows_before
    assert (world.old / "notes.md").read_text() == "x" and not target.exists()
    merged = world.projects / enc(str(world.old))
    assert sorted(str(p.relative_to(merged)) for p in merged.rglob("*") if p.is_file()) == [
        "memory/a.md", "memory/b.md", "short.jsonl", "t.jsonl"]
    assert not world.short.exists()


def test_a_repoint_reverse_says_to_move_the_folder_back_by_hand(world):
    os.rename(world.old, world.new)
    forward = plan_for(world, move_folder=False)
    with closing(connect(world.db, create=False)) as conn:
        reverse = apply_plan(conn, forward, state_dir=world.state)["reverse"]
    assert reverse["move_folder"] is False and "move the folder back by hand" in reverse["note"]
