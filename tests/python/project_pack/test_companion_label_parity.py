
from __future__ import annotations

import pytest

from src.config import settings  # noqa: F401

from src.core.companion_shell.rows import companion_labels, shell_label
from tests.python.project_pack.pack_world import conn_of


@pytest.mark.parametrize("shell,parent,title,claude_title,expected", [
    ("carnivore_sh-4", "carnivore_my_api", None, None, "the terminal shell of my api"),
    ("cloude_sh-4", "cloude_my_api", "", None, "the terminal shell of my api"),
    ("cloude_sh-4", "carnivore_api", "  api work ", None, "the terminal shell of api work"),
    ("carnivore_sh-4", "carnivore_my_api", "", "claude named", "the terminal shell of my api"),
])
def test_companion_label_matches_sidebar(world, shell, parent, title, claude_title, expected):
    with conn_of(world) as conn:
        cur = conn.execute(
            "INSERT INTO sessions (session_uuid, working_dir, origin, lifecycle, tmux_name, title, claude_title, created_at, "
            "updated_at) VALUES ('a1', '/elsewhere', 'created', 'stopped', ?, ?, ?, 'n', 'n')", (parent, title, claude_title))
        conn.execute(
            "INSERT INTO sessions (session_uuid, working_dir, origin, lifecycle, tmux_name, tmux_created_epoch, companion_of, "
            "created_at, updated_at) VALUES ('sh1', '/x', 'created', 'running', ?, 1, ?, 'n', 'n')", (shell, cur.lastrowid))
        labels = companion_labels(conn)
    assert shell_label(shell, labels) == expected
