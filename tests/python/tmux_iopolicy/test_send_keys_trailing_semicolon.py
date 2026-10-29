
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ssk_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ssk_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.tmux_backend import TmuxBackend
from tests.socket_guard import derive_test_socket

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="real tmux binary not available")


def _tmux(socket: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", "-L", socket, *args], capture_output=True, text=True,
                          check=False, timeout=15)


@pytest.fixture()
def pane(tmp_path, monkeypatch):
    out = tmp_path / "pane_bytes"
    socket = derive_test_socket("send_keys_semi")
    made = _tmux(socket, "new-session", "-d", "-s", "semi", "-x", "120", "-y", "30",
                 f"sh -c 'stty raw -echo; cat > {out}'")
    assert made.returncode == 0, made.stderr
    monkeypatch.setenv("CARNIVORE_CONTROL_INPUT", "0")
    backend = TmuxBackend(session_id="sess-semi", working_dir=tmp_path,
                          socket_name=socket, session_name="semi")
    backend._running = True
    try:
        time.sleep(0.3)
        yield out, backend
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
@pytest.mark.parametrize("text", ["trail;", "a;b;", ";", "x\;", "mid;dle"])
async def test_semicolons_arrive_byte_exact(pane, text):
    out, backend = pane
    await backend.write(text.encode())
    assert _wait_for(out, text.encode()) == text.encode()
