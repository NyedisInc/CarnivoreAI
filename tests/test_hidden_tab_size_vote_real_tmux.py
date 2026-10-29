
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import List, Tuple

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_hts_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_hts_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
import src.api.ws_receive as ws_module
from src.api.ws_receive import receive_messages
from src.core.session_manager import SessionManager
from src.core.sessions.registry import SessionRegistry
from src.core.tmux_backend import TmuxBackend
from src.models import Session, SessionStatus
from tests.socket_guard import derive_test_socket

pytestmark = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="real tmux binary not available"
)

BIRTH = (200, 60)

SESSION_ID = "sess-hidden-vote"
TMUX_NAME = "hidden_vote"


class _StopLoop(Exception):
    pass


class FakeWebSocket:

    def __init__(self) -> None:
        self._frames: List[dict] = []

    def queue(self, cols: int, rows: int, hidden: bool | None) -> None:
        frame = {"type": "pty_resize", "cols": cols, "rows": rows}
        if hidden is not None:
            frame["hidden"] = hidden
        self._frames.append({"text": json.dumps(frame)})

    async def receive(self) -> dict:
        if not self._frames:
            raise _StopLoop()
        return self._frames.pop(0)


class RecordingConnections:

    def __init__(self) -> None:
        self.frames: List[dict] = []

    async def broadcast_to_session(self, session_id: str, message: str) -> None:
        self.frames.append(json.loads(message))


def _tmux(socket: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", "-L", socket, *args],
                          capture_output=True, text=True, check=False, timeout=15)


def _pane_size(socket: str) -> Tuple[int, int]:
    result = _tmux(socket, "display-message", "-p", "-t", TMUX_NAME,
                   "#{pane_width} #{pane_height}")
    parts = result.stdout.split()
    assert len(parts) == 2, f"tmux gave no geometry: {result!r}"
    return int(parts[0]), int(parts[1])


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    socket = derive_test_socket("hidden_vote")
    made = _tmux(socket, "new-session", "-d", "-s", TMUX_NAME,
                 "-x", str(BIRTH[0]), "-y", str(BIRTH[1]), "sleep 300")
    assert made.returncode == 0, f"tmux new-session failed: {made.stderr}"
    _tmux(socket, "set-option", "-t", TMUX_NAME, "window-size", "manual")
    assert _pane_size(socket) == BIRTH, "the fixture pane is not at birth size"

    backend = TmuxBackend(session_id=SESSION_ID, working_dir=tmp_path,
                          socket_name=socket, session_name=TMUX_NAME)
    registry = SessionRegistry(log_cap=lambda: 1000)
    registry.register(
        Session(id=SESSION_ID, working_dir=str(tmp_path),
                status=SessionStatus.RUNNING, tmux_session=TMUX_NAME),
        backend,
    )
    manager = SimpleNamespace(_registry=registry)
    manager.resize_terminal = SessionManager.resize_terminal.__get__(manager)
    connections = RecordingConnections()
    monkeypatch.setattr(ws_module, "connection_manager", connections)
    try:
        yield socket, manager, connections
    finally:
        _tmux(socket, "kill-server")


async def _send(manager, ws: FakeWebSocket, cols: int, rows: int,
                hidden: bool | None) -> None:
    ws.queue(cols, rows, hidden)
    with pytest.raises(_StopLoop):
        await receive_messages(ws, manager, session_id=SESSION_ID)
    time.sleep(0.05)


@pytest.mark.asyncio
async def test_the_pane_follows_the_visible_window_when_the_other_goes_hidden(rig):
    socket, manager, connections = rig
    owner, brave = FakeWebSocket(), FakeWebSocket()

    await _send(manager, owner, 160, 47, hidden=False)
    assert _pane_size(socket) == (160, 47)

    await _send(manager, brave, 82, 30, hidden=False)
    assert _pane_size(socket) == (82, 30)

    await _send(manager, brave, 82, 30, hidden=True)
    assert _pane_size(socket) == (160, 47)
    assert connections.frames[-1]["cols"] == 160
    assert connections.frames[-1]["rows"] == 47

    await _send(manager, brave, 60, 20, hidden=True)
    assert _pane_size(socket) == (160, 47)

    await _send(manager, owner, 160, 47, hidden=True)
    assert _pane_size(socket) == (160, 47)

    await _send(manager, brave, 82, 30, hidden=False)
    assert _pane_size(socket) == (82, 30)


@pytest.mark.asyncio
async def test_a_client_that_never_says_hidden_still_votes(rig):
    socket, manager, _connections = rig
    owner, old = FakeWebSocket(), FakeWebSocket()

    await _send(manager, owner, 160, 47, hidden=False)
    await _send(manager, old, 82, 30, hidden=None)
    assert _pane_size(socket) == (82, 30)


@pytest.mark.asyncio
async def test_a_lone_hidden_tab_is_told_the_pane_it_did_not_choose(rig):
    from src.api.resize_negotiation import apply_negotiated_resize, release_client_resize

    socket, manager, connections = rig
    joe, brave = FakeWebSocket(), FakeWebSocket()
    await _send(manager, joe, 100, 39, hidden=False)
    await _send(manager, brave, 105, 40, hidden=True)
    assert _pane_size(socket) == (100, 39)

    await release_client_resize(manager, SESSION_ID, joe, connections)
    assert _pane_size(socket) == (100, 39)

    connections.frames.clear()
    await _send(manager, brave, 105, 40, hidden=True)
    assert _pane_size(socket) == (100, 39)
    assert connections.frames, "a lone hidden tab was told nothing"
    assert (connections.frames[-1]["cols"], connections.frames[-1]["rows"]) == (100, 39)

    await release_client_resize(manager, SESSION_ID, brave, connections)
    connections.frames.clear()
    again = FakeWebSocket()
    await apply_negotiated_resize(
        manager, SESSION_ID, again, 105, 40, connections,
        known_pane_size=_pane_size(socket), hidden=True)
    assert _pane_size(socket) == (100, 39), "a hidden handshake moved the pane"
    assert connections.frames, "a hidden reconnect was told nothing"
    assert (connections.frames[-1]["cols"], connections.frames[-1]["rows"]) == (100, 39)
