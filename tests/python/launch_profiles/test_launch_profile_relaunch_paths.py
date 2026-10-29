
from __future__ import annotations

import json
import subprocess
from contextlib import closing
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.api import imported_restart_routes, recreate_routes, session_fork_routes, session_sleep_routes
from src.api.imported_restart_routes import ImportedRestartRequest
from src.api.launch_profile_errors import refuse_gone_profile
from src.api.recreate_action import recreate_by_uuid
from src.config import settings
from src.core.db import connect, db_path_for
from src.core.session_recreate_presence import TMUX_GONE, TmuxPresence
from src.core.tmux_backend import TmuxBackend
from tests.python.launch_profiles.test_launch_profile_restart_replay import _create, _set_record, env  # noqa: F401


@pytest.fixture
def starts(env, monkeypatch):  # noqa: F811
    seen = []
    swapped = TmuxBackend.start

    async def spy(self, command=None, env=None, **kw):
        seen.append(command)
        return await swapped(self, command=command, env=env, **kw)

    monkeypatch.setattr(TmuxBackend, "start", spy)
    monkeypatch.setattr(recreate_routes, "_measure_presence", lambda name, socket: TmuxPresence(TMUX_GONE, "gone"))
    return seen


def _db(env):  # noqa: F811
    return connect(db_path_for(env.state_dir))


def _record(env, uuid):  # noqa: F811
    with closing(_db(env)) as conn:
        return json.loads(conn.execute("SELECT launch_record FROM sessions WHERE session_uuid = ?", (uuid,)).fetchone()[0])


async def _slept_row(env, mgr, session, *, imported=False):  # noqa: F811
    subprocess.run(["tmux", "-L", env.socket, "kill-session", "-t", f"={session.tmux_session}"], check=False)
    with closing(_db(env)) as conn:
        uuid = conn.execute("SELECT session_uuid FROM sessions WHERE tmux_name = ?", (session.tmux_session,)).fetchone()[0]
        conn.execute("UPDATE sessions SET lifecycle='stopped', lifecycle_source='slept_by_user' WHERE session_uuid = ?", (uuid,))
        if imported:
            conn.execute("UPDATE sessions SET tmux_name=NULL, tmux_created_epoch=NULL WHERE session_uuid = ?", (uuid,))
    return uuid


def _request(mgr):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session_manager=mgr)))


@pytest.mark.asyncio
async def test_wake_recreate_and_imported_restart_replay_the_same_plan(env, starts, monkeypatch):  # noqa: F811
    monkeypatch.setattr(session_sleep_routes.session_change_notice, "publish", lambda *a, **k: None)
    monkeypatch.setattr(session_sleep_routes.restart_inflight, "claim", lambda uuid: _NoClaim())
    plans = []
    for path in ("wake", "recreate", "imported"):
        mgr, session = await _create(env, "claude-ask", model="opus-x")
        first = None
        try:
            uuid = await _slept_row(env, mgr, session, imported=path == "imported")
            with closing(_db(env)) as conn:
                first = json.loads(conn.execute("SELECT launch_record FROM sessions WHERE session_uuid = ?", (uuid,)).fetchone()[0])
            before = len(starts)
            if path == "wake":
                out = await session_sleep_routes.wake_session(_request(mgr), uuid, None)
            elif path == "recreate":
                out = await recreate_by_uuid(uuid, "claude-ask", get_manager=lambda: mgr)
            else:
                out = await imported_restart_routes._imported_restart(
                    _request(mgr), ImportedRestartRequest(session_uuid=uuid, agent_type="claude-ask"))
            assert out.status == "started", out.detail
            command = starts[before]
            assert "--model" in command and "opus-x" in command, path
            record = _record(env, uuid)
            plans.append((record["model"], record["account"], record["digest"], record["profile"]))
            assert plans[-1] == (first["model"], first["account"], first["digest"], "claude-ask")
        finally:
            with closing(_db(env)) as conn:
                names = [r[0] for r in conn.execute("SELECT tmux_name FROM sessions WHERE tmux_name IS NOT NULL")]
            for name in names:
                subprocess.run(["tmux", "-L", env.socket, "kill-session", "-t", f"={name}"], check=False)
    assert len({json.dumps(p, sort_keys=True) for p in plans}) == 1


class _NoClaim:

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_a_deleted_profile_is_refused_by_name_on_every_path(env, starts, monkeypatch):  # noqa: F811
    monkeypatch.setattr(session_sleep_routes.restart_inflight, "claim", lambda uuid: _NoClaim())
    mgr, session = await _create(env, "claude-or")
    record = None
    try:
        uuid = await _slept_row(env, mgr, session)
        with closing(_db(env)) as conn:
            record = conn.execute("SELECT launch_record FROM sessions WHERE session_uuid = ?", (uuid,)).fetchone()[0]
        del env.profiles[1]
        before = len(starts)
        woken = await session_sleep_routes.wake_session(_request(mgr), uuid, None)
        assert woken.status == "refused" and woken.codes == ["wrapper_needed", "launch_profile_needed"]
        assert "claude-or" in woken.detail
        recreated = await recreate_by_uuid(uuid, "claude-or", get_manager=lambda: mgr)
        assert recreated.status == "refused" and "claude-or" in recreated.detail
        assert recreated.code == "wrapper_needed" and recreated.codes == ["wrapper_needed", "launch_profile_needed"]
        with closing(_db(env)) as conn:
            conn.execute("UPDATE sessions SET tmux_name=NULL, tmux_created_epoch=NULL WHERE session_uuid = ?", (uuid,))
        imported = await imported_restart_routes._imported_restart(
            _request(mgr), ImportedRestartRequest(session_uuid=uuid, agent_type="claude-or"))
        assert imported.status == "refused" and "claude-or" in imported.detail
        assert imported.code == "wrapper_needed" and imported.codes == ["wrapper_needed", "launch_profile_needed"]
        for agent_type in ("claude-or", "claude"):
            with pytest.raises(HTTPException) as gone:
                refuse_gone_profile(settings, agent_type, record)
            assert gone.value.status_code == 400
            assert gone.value.detail["codes"] == ["wrapper_needed", "launch_profile_needed"]
            assert gone.value.detail["profile"] == "claude-or"
        refuse_gone_profile(settings, "claude-or", None)
        assert len(starts) == before, "nothing may be started"
    finally:
        subprocess.run(["tmux", "-L", env.socket, "kill-session", "-t", f"={session.tmux_session}"], check=False)


@pytest.mark.asyncio
async def test_fork_records_its_own_launch_record_and_a_legacy_parent_is_unchanged(env, starts):  # noqa: F811
    mgr, parent = await _create(env, "claude-ask", model="opus-x")
    child_name = None
    try:
        with closing(_db(env)) as conn:
            conn.execute("UPDATE sessions SET claude_session_uuid = ? WHERE tmux_name = ?",
                         ("11111111-2222-4333-8444-555555555555", parent.tmux_session))
        out = await session_fork_routes.fork_session(_request(mgr), parent.tmux_session)
        child_name = out.session.get("tmux_session") if hasattr(out.session, "get") else out.session["tmux_session"]
        command = starts[-1]
        assert "--fork-session" in command and command.count("--resume") == 1 and "opus-x" in command
        with closing(_db(env)) as conn:
            record = json.loads(conn.execute("SELECT launch_record FROM sessions WHERE tmux_name = ?", (child_name,)).fetchone()[0])
        assert record["profile"] == "claude-ask" and record["model"] == "opus-x"
        _set_record(env, parent, None)
        refuse_gone_profile(settings, "claude-ask", None)
        again = await session_fork_routes.fork_session(_request(mgr), parent.tmux_session)
        assert again.session is not None
    finally:
        with closing(_db(env)) as conn:
            names = [r[0] for r in conn.execute("SELECT tmux_name FROM sessions WHERE tmux_name IS NOT NULL")]
        for name in names:
            subprocess.run(["tmux", "-L", env.socket, "kill-session", "-t", f"={name}"], check=False)
