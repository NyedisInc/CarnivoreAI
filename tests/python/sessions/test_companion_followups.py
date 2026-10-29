
from __future__ import annotations

from contextlib import closing

import pytest

from src.core.companion_shell.index import CompanionIndex
from src.core.db import connect, db_path_for
from src.core.project_archive import archive_project_and_sessions
from src.core.project_writes import create_project
from src.core.session_boot_readopt import readopt_surviving_sessions
from src.core.session_manager import SessionManager
from tests.test_boot_readopt import (  # noqa: F401
    EPOCH_A,
    EPOCH_B,
    TmuxListing,
    install_backends,
    listing_rows,
    seed_row,
    state_dir,
)
from tests import test_project_archive as _archive_tests
from tests.test_project_authority import state_dir as archive_state_dir  # noqa: F401


def test_relinking_a_companion_drops_its_old_hiding_name():
    index = CompanionIndex()
    index.link(agent_row=1, shell_row=2, tmux_name="carnivore_sh-old")
    index.link(agent_row=1, shell_row=2, tmux_name="carnivore_sh-new")
    assert index.is_hidden_name("carnivore_sh-new")
    assert not index.is_hidden_name("carnivore_sh-old")


def test_archiving_a_project_archives_a_stopped_companion_and_leaves_a_live_one_uncounted(archive_state_dir):
    with closing(connect(db_path_for(archive_state_dir))) as conn:
        project = create_project(conn, name="comp", path="~/comp")
        seed = _archive_tests.TestSessionsAreNotTouched._seed_session
        seed(conn, "agent-live", project["id"], "running")
        seed(conn, "shell-stopped", project["id"], "stopped")
        seed(conn, "agent-live-2", project["id"], "running")
        seed(conn, "shell-live", project["id"], "running")
        ids = {r["session_uuid"]: r["id"] for r in conn.execute("SELECT id, session_uuid FROM sessions")}
        for shell, agent in (("shell-stopped", "agent-live"), ("shell-live", "agent-live-2")):
            conn.execute("UPDATE sessions SET companion_of = ? WHERE session_uuid = ?", (ids[agent], shell))
        conn.commit()
        out = archive_project_and_sessions(conn, project["id"])
        assert out["sessions_archived"] == 1
        assert out["sessions_live"] == 2
        archived = {r[0] for r in conn.execute("SELECT session_uuid FROM sessions WHERE archived_at IS NOT NULL")}
        assert archived == {"shell-stopped"}


@pytest.mark.asyncio
async def test_boot_pick_skips_a_hidden_first_held_session(state_dir, monkeypatch):  # noqa: F811
    mgr = SessionManager()
    for name, epoch in (("cloude_alpha", EPOCH_A), ("cloude_beta", EPOCH_B)):
        seed_row(state_dir, mgr, name=name, epoch=epoch)
    mgr._registry.hide_when(lambda s: s.id == "adopted:cloude_alpha")
    install_backends(
        monkeypatch,
        discover=TmuxListing.answered([]),
        attachable=listing_rows(("cloude_alpha", EPOCH_A), ("cloude_beta", EPOCH_B)),
    )

    await readopt_surviving_sessions(mgr)

    assert mgr._registry.last_session_id == "adopted:cloude_beta"
