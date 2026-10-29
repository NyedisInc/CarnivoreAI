
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
import uuid
from contextlib import closing
from datetime import datetime

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_akv_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_akv_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.config import settings
from src.core.session_manager import SessionManager
from src.core.sessions.registry import SessionRegistry
from src.models import Session, SessionStatus
from tests.s7_helpers import migrated_connection
from tests.socket_guard import TEST_SOCKET_NAME

requires_tmux = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not on PATH")


def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", "-L", TEST_SOCKET_NAME, *args],
                          capture_output=True, text=True, check=False)


def _session(sid: str, tmux_name: str) -> Session:
    return Session(id=sid, pty_pid=None, working_dir="/tmp", status=SessionStatus.RUNNING,
                   created_at=datetime.utcnow(), last_activity=datetime.utcnow(),
                   tmux_session=tmux_name)


def test_parked_viewers_come_back_on_register_and_a_rekey_closes_them():
    reg = SessionRegistry(log_cap=lambda: 100)
    reg.register(_session("ses_a", "cloude_x"), None)
    kept = reg.subscribe("ses_a")
    assert reg.park_viewers("cloude_x", "ses_a") == 1
    reg.forget("ses_a")
    assert not kept.closed, "the teardown closed a parked viewer"
    reg.register(_session("ses_a", "cloude_x"), None)
    assert reg.subscribers["ses_a"] == [kept]

    reg.park_viewers("cloude_x", "ses_a")
    reg.forget("ses_a")
    reg.register(_session("ses_b", "cloude_x"), None)
    assert reg.subscribers["ses_b"] == []
    reg.discard_parked("cloude_x")
    assert kept.closed, "a viewer of a changed id must close"


@requires_tmux
@pytest.mark.asyncio
async def test_a_real_readopt_leaves_the_other_window_connected(tmp_path, monkeypatch):
    log_dir, state, work = tmp_path / "logs", tmp_path / "state", tmp_path / "work"
    for d in (log_dir, state, work):
        d.mkdir()
    monkeypatch.setattr(settings, "log_directory", str(log_dir))
    monkeypatch.setattr(settings, "state_dir_override", str(state))
    with closing(migrated_connection(state)):
        pass
    name = f"cloude_akv_{uuid.uuid4().hex[:6]}"
    made = _tmux("new-session", "-d", "-s", name, "-c", str(work), "-x", "100", "-y", "30",
                 "while true; do echo tick; sleep 0.2; done")
    assert made.returncode == 0, made.stderr
    mgr = SessionManager()
    try:
        first = await mgr.adopt_external_session(name)
        sid = first["session"].id
        other_window = mgr._registry.subscribe(sid)
        second = await mgr.adopt_external_session(name)
        assert second["session"].id == sid
        assert not other_window.closed, "re-adopt closed the other window's socket"
        assert other_window in mgr._registry.subscribers[sid]
        assert mgr._registry._parked_viewers == {}
    finally:
        for backend in list(mgr._registry.backends.values()):
            task = backend._reader_task
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, OSError, RuntimeError):
                    pass
        _tmux("kill-server")
