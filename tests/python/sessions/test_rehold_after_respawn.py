
from __future__ import annotations

import asyncio
import shutil
import subprocess
import uuid
from contextlib import closing
from pathlib import Path

import pytest

from src.config import settings
from src.config.auth import AuthConfig
from src.core.db import connect, db_path_for
from src.core.db_models import SESSION_ORIGIN_CREATED
from src.core.session_identity import record_instance
from src.core.session_manager import SessionManager
from src.core.session_respawn import RESPAWN_AGENT, RespawnResult
from src.core.sessions.rehold_after_respawn import rehold_respawned_session
from src.core.tmux_backend import TmuxBackend
from tests.s7_helpers import migrated_connection
from tests.socket_guard import TEST_SOCKET_NAME

requires_tmux = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not on PATH")


def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", "-L", TEST_SOCKET_NAME, *args], capture_output=True, text=True, check=False)


@pytest.fixture
def stopped_session(tmp_path, monkeypatch):
    state, work = tmp_path / "state", tmp_path / "work"
    for d in (state, work, tmp_path / "logs"):
        d.mkdir()
    monkeypatch.setattr(settings, "log_directory", str(tmp_path / "logs"))
    monkeypatch.setattr(settings, "state_dir_override", str(state))
    with closing(migrated_connection(state)):
        pass
    mgr = SessionManager()
    name, sid = f"cloude_rehold_{uuid.uuid4().hex[:6]}", "ses_rehold1"
    out = _tmux("new-session", "-d", "-s", name, "-c", str(work), "-x", "132", "-y", "40",
                "-e", f"CLOUDECODE_SESSION_ID={sid}")
    assert out.returncode == 0, out.stderr
    epoch = int(_tmux("list-sessions", "-F", "#{session_name}\t#{session_created}").stdout.split("\t")[1])
    with closing(connect(db_path_for(state))) as conn:
        record_instance(conn, socket=mgr.tmux_socket_name(), name=name, epoch=epoch,
                        origin=SESSION_ORIGIN_CREATED, working_dir=str(work))
        conn.commit()
    mgr.hook_tokens.tmux_names = {sid: name}
    try:
        yield mgr, name, sid
    finally:
        for backend in list(mgr._registry.backends.values()):
            task = getattr(backend, "_reader_task", None)
            if task is not None:
                task.cancel()
        _tmux("kill-server")


@requires_tmux
@pytest.mark.asyncio
async def test_rehold_registers_the_surviving_session_under_its_stored_id(stopped_session):
    mgr, name, sid = stopped_session
    assert sid not in mgr._registry.sessions
    assert await rehold_respawned_session(mgr, name) == sid
    assert sid in mgr._registry.sessions and sid in mgr._registry.backends
    assert mgr._registry.backends[sid].tmux_session == name
    assert await rehold_respawned_session(mgr, name) is None


@requires_tmux
@pytest.mark.asyncio
async def test_respawn_of_an_unheld_session_returns_the_live_id_and_lists_it(stopped_session, monkeypatch):
    mgr, name, sid = stopped_session

    async def _ok_respawn(self, **_kwargs):
        return RespawnResult(kind=RESPAWN_AGENT, ok=True, detail="started", command="stub", conversation="resumed")

    monkeypatch.setattr(TmuxBackend, "respawn", _ok_respawn)
    auth = AuthConfig()
    auth.session.tmux_socket_name = TEST_SOCKET_NAME
    monkeypatch.setattr(type(settings), "load_auth_config", lambda self, *a, **k: auth)
    result = await mgr.respawn_session(name, socket_name=mgr.tmux_socket_name())
    assert result["ok"] is True
    assert result["session_id"] == sid
    assert sid in mgr._registry.sessions
    assert mgr._registry.backends[sid].tmux_session == name
