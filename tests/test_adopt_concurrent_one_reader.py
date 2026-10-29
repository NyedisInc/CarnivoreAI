
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
    with closing(migrated_connection(state)):
        pass
    try:
        yield state
    finally:
        _tmux("kill-server")


@requires_tmux
@pytest.mark.asyncio
async def test_concurrent_adopts_leave_one_reader_and_deliver_each_byte_once(
    live_state, tmp_path, monkeypatch
):
    work = tmp_path / "work"
    work.mkdir()
    name = f"cloude_dupadopt_{uuid.uuid4().hex[:6]}"
    result = _tmux(
        "new-session", "-d", "-s", name, "-c", str(work), "-x", "100",
        "-y", "30",
        "i=0; while true; do echo TICK$i; i=$((i+1)); sleep 0.05; done",
    )
    assert result.returncode == 0, result.stderr

    built: List[TmuxBackend] = []
    real_for_external = TmuxBackend.for_external.__func__

    def _recording_for_external(cls, *args, **kwargs):
        backend = real_for_external(cls, *args, **kwargs)
        built.append(backend)
        return backend

    monkeypatch.setattr(
        TmuxBackend, "for_external", classmethod(_recording_for_external)
    )

    mgr = SessionManager()
    published: List[Tuple[str, bytes]] = []
    real_publish = mgr._registry.publish

    def _recording_publish(session_id: str, data: bytes) -> None:
        published.append((session_id, data))
        real_publish(session_id, data)

    mgr._registry.publish = _recording_publish  # type: ignore[method-assign]

    try:
        with capture_logs() as logs:
            first, second = await asyncio.gather(
                mgr.adopt_external_session(name),
                mgr.adopt_external_session(name),
            )
        replaced = [e for e in logs if e["event"] == "registry_replaced_live_backend"]
        assert not replaced, "the adopts interleaved; the lock did not serialize"
        session_id = first["session"].id
        assert second["session"].id == session_id
        published.clear()
        await asyncio.sleep(2.0)

        live = [
            b for b in built
            if b._reader_task is not None and not b._reader_task.done()
        ]
        assert len(built) >= 1
        assert len(live) == 1, (
            f"{len(live)} live tail loops for one pane; expected exactly one"
        )
        assert mgr._registry.backends[session_id] is live[0]
        assert mgr._adopt_locks.held_names() == 0, "a lock outlived its adopts"

        text = b"".join(d for sid, d in published if sid == session_id)
        ticks = re.findall(rb"TICK(\d+)\r?\n", text)
        assert len(ticks) >= 10, f"population check: saw {len(ticks)} ticks"
        assert len(ticks) == len(set(ticks)), (
            f"{len(ticks)} ticks delivered for {len(set(ticks))} distinct: "
            "bytes were published more than once"
        )
    finally:
        for backend in built:
            task = backend._reader_task
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, OSError, RuntimeError):
                    pass


@pytest.mark.asyncio
async def test_name_locks_serialize_one_name_and_not_two():
    from src.core.sessions.name_locks import NameLocks

    locks = NameLocks()
    order: List[str] = []

    async def _hold(name: str, tag: str) -> None:
        async with locks.hold(name):
            order.append(f"{tag}+")
            await asyncio.sleep(0.02)
            order.append(f"{tag}-")

    await asyncio.gather(_hold("a", "1"), _hold("a", "2"))
    assert order == ["1+", "1-", "2+", "2-"]
    order.clear()
    await asyncio.gather(_hold("a", "1"), _hold("b", "2"))
    assert order[:2] == ["1+", "2+"], "a different name waited"
    assert locks.held_names() == 0


class _FakeBackend:

    def __init__(self, task: "asyncio.Task[None]") -> None:
        self._reader_task = task
        self._running = True
        self.tmux_session = "cloude_fake"


def _session(sid: str) -> Session:
    from datetime import datetime

    return Session(
        id=sid, pty_pid=None, working_dir="/tmp",
        status=SessionStatus.RUNNING, created_at=datetime.utcnow(),
        last_activity=datetime.utcnow(),
    )


@pytest.mark.asyncio
async def test_register_stops_the_reader_of_a_backend_it_replaces():
    registry = SessionRegistry(log_cap=lambda: 100)
    old = _FakeBackend(asyncio.create_task(asyncio.sleep(3600)))
    new = _FakeBackend(asyncio.create_task(asyncio.sleep(3600)))
    old_task, new_task = old._reader_task, new._reader_task
    try:
        registry.register(_session("ses_a"), old)
        registry.register(_session("ses_a"), old)
        await asyncio.sleep(0)
        assert not old_task.done(), "re-registering itself stopped it"

        registry.register(_session("ses_a"), new)
        await asyncio.sleep(0.01)
        assert registry.backends["ses_a"] is new
        assert old_task.cancelled(), "replaced reader still running"
        assert old._running is False
        assert not new_task.done()
    finally:
        for task in (old_task, new_task):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
