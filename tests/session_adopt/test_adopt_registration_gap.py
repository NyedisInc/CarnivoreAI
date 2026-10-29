
from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from contextlib import closing
from pathlib import Path
from typing import List, Tuple

import pytest
from fastapi import HTTPException
from structlog.testing import capture_logs

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_aco_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_aco_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.config import settings
from src.core.session_manager import SessionManager
from src.core.sessions.registry import SessionRegistry
from src.core.tmux_backend import TmuxBackend
from src.models import Session, SessionStatus
from tests.s7_helpers import migrated_connection
from tests.socket_guard import TEST_SOCKET_NAME

requires_tmux = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux not on PATH"
)


def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["tmux", "-L", TEST_SOCKET_NAME, *args],
        capture_output=True, text=True, check=False,
    )


@pytest.fixture
def live_state(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    state = tmp_path / "state"
    log_dir.mkdir()
    state.mkdir()
    monkeypatch.setattr(settings, "log_directory", str(log_dir))
    monkeypatch.setattr(settings, "state_dir_override", str(state))
    (tmp_path / "config.json").write_text("{}")
    monkeypatch.chdir(tmp_path)
    with closing(migrated_connection(state)):
        pass
    try:
        yield state
    finally:
        _tmux("kill-server")




class _Req:

    def __init__(self, mgr, session_id: str, token: str) -> None:
        from types import SimpleNamespace

        self.client = SimpleNamespace(host="127.0.0.1")
        self.scope: dict = {}
        self.headers = {
            "authorization": f"Bearer {token}",
            "x-carnivore-session": session_id,
        }
        self.app = SimpleNamespace(state=SimpleNamespace(session_manager=mgr))
        self.url = SimpleNamespace(path="/x")
        self.method = "POST"


def _request(mgr, session_id: str) -> "_Req":
    from src.api import agent_auth

    req = _Req(mgr, session_id, mgr.hook_tokens.tokens[session_id])
    req.headers[agent_auth.SESSION_HEADER] = session_id
    return req


async def _adopt_with_mid_gap_call(mgr, name, monkeypatch, fail=False):
    from src.api.agent_auth import require_agent

    first = await mgr.adopt_external_session(name)
    sid = first["session"].id
    req = _request(mgr, sid)
    assert mgr._registry.registered_ids_for_tmux_name(name)
    real_attach = TmuxBackend.attach_existing
    seen: List[object] = []

    async def _attach_task(self, *a, **kw):
        task = asyncio.ensure_future(require_agent(req))
        await asyncio.sleep(0.05)
        assert not task.done(), "agent was not made to wait"
        if fail:
            raise RuntimeError("attach failed")
        res = await real_attach(self, *a, **kw)
        seen.append(task)
        return res

    monkeypatch.setattr(TmuxBackend, "attach_existing", _attach_task)
    try:
        await mgr.adopt_external_session(name)
    except RuntimeError:
        pass
    return sid, seen, req


def _new_pane(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    name = f"cloude_gap_{uuid.uuid4().hex[:6]}"
    r = _tmux("new-session", "-d", "-s", name, "-c", str(work), "-x", "100", "-y", "30", "sleep 600")
    assert r.returncode == 0, r.stderr
    return name


@requires_tmux
@pytest.mark.asyncio
async def test_agent_call_during_readopt_gap_is_not_refused(live_state, tmp_path, monkeypatch):
    name = _new_pane(tmp_path)
    mgr = SessionManager()
    sid, seen, _ = await _adopt_with_mid_gap_call(mgr, name, monkeypatch)
    assert len(seen) == 1
    caller = await seen[0]
    assert caller.session_id == sid
    assert mgr._pending_agent_registration == {}
    for b in list(mgr._registry.backends.values()):
        t = getattr(b, "_reader_task", None)
        if t is not None:
            t.cancel()


@requires_tmux
@pytest.mark.asyncio
async def test_failed_readopt_releases_the_waiter(live_state, tmp_path, monkeypatch):
    name = _new_pane(tmp_path)
    mgr = SessionManager()
    from src.api.agent_auth import require_agent

    first = await mgr.adopt_external_session(name)
    sid = first["session"].id
    req = _request(mgr, sid)
    waiter: List[asyncio.Future] = []

    async def _boom(self, *a, **kw):
        waiter.append(asyncio.ensure_future(require_agent(req)))
        await asyncio.sleep(0.05)
        assert not waiter[0].done()
        raise RuntimeError("attach failed")

    monkeypatch.setattr(TmuxBackend, "attach_existing", _boom)
    with pytest.raises(RuntimeError):
        await mgr.adopt_external_session(name)
    with pytest.raises(HTTPException) as exc:
        await asyncio.wait_for(waiter[0], timeout=1)
    assert exc.value.status_code == 401
    assert mgr._pending_agent_registration == {}
