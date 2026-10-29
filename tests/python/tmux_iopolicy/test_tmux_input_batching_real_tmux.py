
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_inb_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_inb_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.api.ws_input_pipeline import InputPipeline
from src.api.ws_receive import receive_messages
from src.core.sessions.registry import SessionRegistry
from src.core.tmux_backend import TmuxBackend
from src.models import Session, SessionStatus
from tests.socket_guard import derive_test_socket

pytestmark = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="real tmux binary not available"
)

SESSION_ID = "sess-input-batch"
TMUX_NAME = "input_batch"


class _StopLoop(Exception):
    pass


class FakeWebSocket:

    def __init__(self, frames: list[bytes]) -> None:
        self._frames = list(frames)
        self.scope: dict = {}
        self.app = None

    async def receive(self) -> dict:
        await asyncio.sleep(0)
        if not self._frames:
            raise _StopLoop()
        return {"bytes": self._frames.pop(0)}


def _tmux(socket: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", "-L", socket, *args],
                          capture_output=True, text=True, check=False, timeout=15)


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    out = tmp_path / "pane_bytes"
    socket = derive_test_socket("input_batch")
    made = _tmux(socket, "new-session", "-d", "-s", TMUX_NAME, "-x", "120", "-y", "30",
                 f"sh -c 'stty raw -echo; cat > {out}'")
    assert made.returncode == 0, f"tmux new-session failed: {made.stderr}"
    backend = TmuxBackend(session_id=SESSION_ID, working_dir=tmp_path,
                          socket_name=socket, session_name=TMUX_NAME)
    backend._running = True
    registry = SessionRegistry(log_cap=lambda: 1000)
    registry.register(Session(id=SESSION_ID, working_dir=str(tmp_path),
                              status=SessionStatus.RUNNING, tmux_session=TMUX_NAME), backend)

    async def send_input(text: str, session_id=None) -> bool:
        await backend.write(text.encode("utf-8"))
        return True

    async def no_owner_input(app, session_id) -> None:
        return None

    monkeypatch.setattr("src.core.crosstalk.contacts.owner_input", no_owner_input)
    monkeypatch.setenv("CARNIVORE_CONTROL_INPUT", "0")
    spawns: list[str] = []
    real_run = TmuxBackend._run_tmux

    async def counting_run(self, *args, **kwargs):
        if args and args[0] == "send-keys":
            spawns.append(args[1])
        return await real_run(self, *args, **kwargs)

    monkeypatch.setattr(TmuxBackend, "_run_tmux", counting_run)
    manager = SimpleNamespace(send_input=send_input)
    try:
        time.sleep(0.3)
        yield out, manager, spawns
    finally:
        _tmux(socket, "kill-server")


def _wait_for(path: Path, expected: bytes, timeout: float = 8.0) -> bytes:
    deadline = time.monotonic() + timeout
    got = b""
    while time.monotonic() < deadline:
        got = path.read_bytes() if path.exists() else b""
        if got == expected:
            break
        time.sleep(0.05)
    return got


@pytest.mark.asyncio
async def test_a_twenty_frame_burst_arrives_byte_exact_in_order_with_far_fewer_spawns(rig):
    out, manager, spawns = rig
    frames = [c.encode() for c in "abcdefghij"] + [b"\x7f", b"-", b"\x1b[A", "é".encode(),
                                                   b"k", b"l", b"m", b"n", b"o", b"p"]
    assert len(frames) == 20
    ws = FakeWebSocket(frames)
    with pytest.raises(_StopLoop):
        await receive_messages(ws, manager, session_id=SESSION_ID)
    expected = b"".join(frames)
    assert _wait_for(out, expected) == expected
    assert 1 <= len(spawns) <= 6, f"20 frames should coalesce into a few sends, got {len(spawns)}"


@pytest.mark.asyncio
async def test_pipeline_keeps_order_caps_batches_and_drains_on_close():
    sent: list[str] = []
    failures: list[int] = []
    gate = asyncio.Event()

    async def send(batch: str) -> None:
        await gate.wait()
        if batch.startswith("boom"):
            raise RuntimeError("tmux said no")
        sent.append(batch)

    pipe = InputPipeline(send, lambda exc, size: failures.append(size), max_batch_bytes=8)
    for text in ("ab", "cd", "ef", "gh", "ij", "boomboom", "x" * 20, "yz"):
        await pipe.submit(text)
    gate.set()
    await pipe.close()
    assert sent == ["abcdefgh", "ij", "x" * 20, "yz"]
    assert failures == [8]
