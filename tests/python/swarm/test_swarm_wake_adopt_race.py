
from __future__ import annotations

import asyncio
import subprocess
from contextlib import closing
from types import SimpleNamespace

import pytest

from src.api import recreate_routes
from src.core.db import connect, db_path_for
from src.core.session_recreate_presence import TMUX_GONE, TmuxPresence
from src.core.swarm import body, body_create
from src.core.tmux_backend import TmuxBackend
from tests.python.launch_profiles.test_launch_profile_relaunch_paths import _slept_row
from tests.python.launch_profiles.test_launch_profile_restart_replay import _create, env  # noqa: F401


@pytest.mark.asyncio
async def test_a_tab_readopting_mid_wake_leaves_the_body_on_the_agents_row(env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(recreate_routes, "_measure_presence", lambda name, socket: TmuxPresence(TMUX_GONE, "gone"))
    monkeypatch.setattr(body_create, "write_settings", lambda *a, **k: None)
    monkeypatch.setattr(body_create, "write_definition", lambda *a, **k: None)
    mgr, session = await _create(env, "claude-ask")
    name = session.tmux_session
    uuid = await _slept_row(env, mgr, session)
    with closing(connect(db_path_for(env.state_dir))) as conn:
        row_id = conn.execute("SELECT id FROM sessions WHERE session_uuid = ?", (uuid,)).fetchone()[0]
        conn.execute("UPDATE sessions SET tmux_created_epoch = tmux_created_epoch - 3600 WHERE id = ?", (row_id,))
        conn.commit()
    adopts = []
    started = TmuxBackend.start

    async def start_then_tab_readopts(self, command=None, env=None, **kw):
        out = await started(self, command=command, env=env, **kw)
        if not adopts:
            adopts.append(asyncio.create_task(mgr.adopt_external_session(name, confirm_detach=True)))
            await asyncio.wait(adopts, timeout=3)
        return out

    monkeypatch.setattr(TmuxBackend, "start", start_then_tab_readopts)
    agent = {"id": 1, "host_key": "local", "session_row_id": row_id, "parent_id": None, "harness": "claude"}
    try:
        ident = await body._start(SimpleNamespace(session_manager=mgr), agent, "resume")
        await asyncio.gather(*adopts)
        assert adopts, "the tab's re-adopt never ran"
        assert ident.row_id == row_id
        with closing(connect(db_path_for(env.state_dir))) as conn:
            rows = conn.execute("SELECT id FROM sessions WHERE tmux_name = ? AND tmux_created_epoch = ?",
                                (name, ident.tmux_epoch)).fetchall()
        assert [r[0] for r in rows] == [row_id], "a second row took the new pane"
        assert (await mgr.get_session_info(ident.session_id)).session_row_id == row_id
    finally:
        subprocess.run(["tmux", "-L", env.socket, "kill-session", "-t", f"={name}"], check=False)
