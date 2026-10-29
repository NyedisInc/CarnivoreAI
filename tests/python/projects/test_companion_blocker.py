
from __future__ import annotations

from contextlib import closing

import pytest

from src.config import settings  # noqa: F401

from src.core.db import connect
from tests.python.projects.move_world import NO_PANES, plan_for


@pytest.mark.parametrize("orphan", [False, True])
def test_move_blocker_names_the_agents_terminal_shell(world, orphan):
    with closing(connect(world.db, create=False)) as conn:
        cur = conn.execute(
            "INSERT INTO sessions (session_uuid, working_dir, origin, lifecycle, tmux_name, title, created_at, updated_at) "
            "VALUES ('a1', '/elsewhere', 'created', 'stopped', 'carnivore_agent', 'api work', 'n', 'n')")
        conn.execute(
            "INSERT INTO sessions (session_uuid, working_dir, origin, lifecycle, tmux_name, tmux_created_epoch, companion_of, "
            "created_at, updated_at) VALUES ('sh1', ?, 'created', 'running', 'carnivore_sh-4', 1, ?, 'n', 'n')",
            (str(world.sub), cur.lastrowid + (100 if orphan else 0)))
        conn.commit()
    plan = plan_for(world, move_folder=True, panes=NO_PANES)
    blocked = [c["message"] for c in plan.checks if c["id"] == "no_live_sessions" and not c["ok"]]
    assert len(blocked) == 1 and "carnivore_sh-" not in blocked[0]
    assert ("an open terminal shell" if orphan else "the terminal shell of api work") in blocked[0]


def test_move_blocker_never_prints_a_hidden_pane_with_no_row_or_a_prefixed_parent(world):
    from src.core.project_move.plan import PaneListing
    with closing(connect(world.db, create=False)) as conn:
        cur = conn.execute(
            "INSERT INTO sessions (session_uuid, working_dir, origin, lifecycle, tmux_name, created_at, updated_at) "
            "VALUES ('a1', '/elsewhere', 'created', 'stopped', 'carnivore_api', 'n', 'n')")
        conn.execute(
            "INSERT INTO sessions (session_uuid, working_dir, origin, lifecycle, tmux_name, tmux_created_epoch, companion_of, "
            "created_at, updated_at) VALUES ('sh1', ?, 'created', 'running', 'carnivore_sh-4', 1, ?, 'n', 'n')",
            (str(world.sub), cur.lastrowid))
        conn.commit()
    panes = PaneListing(ok=True, panes=(("carnivore_sh-9", 2, str(world.sub)),))
    plan = plan_for(world, move_folder=True, panes=panes)
    blocked = [c["message"] for c in plan.checks if c["id"] == "no_live_sessions" and not c["ok"]]
    assert len(blocked) == 1 and "carnivore_sh-" not in blocked[0]
    assert "the terminal shell of api" in blocked[0] and "carnivore_api" not in blocked[0]
    assert "an open terminal shell" in blocked[0]
