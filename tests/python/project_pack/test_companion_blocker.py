
from __future__ import annotations

import pytest

from src.config import settings  # noqa: F401

from tests.python.project_pack.pack_world import conn_of, pack_plan


@pytest.mark.parametrize("orphan", [False, True])
def test_pack_blocker_names_the_agents_terminal_shell(world, orphan):
    with conn_of(world) as conn:
        cur = conn.execute(
            "INSERT INTO sessions (session_uuid, working_dir, origin, lifecycle, tmux_name, title, created_at, updated_at) "
            "VALUES ('a1', '/elsewhere', 'created', 'stopped', 'carnivore_agent', 'api work', 'n', 'n')")
        conn.execute(
            "INSERT INTO sessions (session_uuid, working_dir, origin, lifecycle, tmux_name, tmux_created_epoch, companion_of, "
            "created_at, updated_at) VALUES ('sh1', ?, 'created', 'running', 'carnivore_sh-4', 1, ?, 'n', 'n')",
            (str(world.root / "src"), cur.lastrowid + (100 if orphan else 0)))
    plan = pack_plan(world)
    blocked = [c["message"] for c in plan.checks if c["id"] == "no_live_sessions" and not c["ok"]]
    assert len(blocked) == 1 and "carnivore_sh-" not in blocked[0]
    assert ("an open terminal shell" if orphan else "the terminal shell of api work") in blocked[0]


def test_pack_blocker_never_prints_a_hidden_pane_with_no_row_or_a_prefixed_parent(world):
    from src.core.project_move.plan import PaneListing
    with conn_of(world) as conn:
        cur = conn.execute(
            "INSERT INTO sessions (session_uuid, working_dir, origin, lifecycle, tmux_name, created_at, updated_at) "
            "VALUES ('a1', '/elsewhere', 'created', 'stopped', 'carnivore_api', 'n', 'n')")
        conn.execute(
            "INSERT INTO sessions (session_uuid, working_dir, origin, lifecycle, tmux_name, tmux_created_epoch, companion_of, "
            "created_at, updated_at) VALUES ('sh1', ?, 'created', 'running', 'carnivore_sh-4', 1, ?, 'n', 'n')",
            (str(world.root / "src"), cur.lastrowid))
    panes = PaneListing(ok=True, panes=(("carnivore_sh-9", 2, str(world.root / "src")),))
    blocked = [c["message"] for c in pack_plan(world, panes=panes).checks if c["id"] == "no_live_sessions" and not c["ok"]]
    assert len(blocked) == 1 and "carnivore_sh-" not in blocked[0]
    assert "the terminal shell of api" in blocked[0] and "carnivore_api" not in blocked[0]
    assert "an open terminal shell" in blocked[0]
