
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_aip_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_aip_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.shell_init import rc_prefixed
from src.core.tmux_backend import TmuxBackend
from tests.socket_guard import derive_test_socket

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="real tmux binary not available")


def _tmux(socket: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", "-L", socket, *args], capture_output=True, text=True, check=False, timeout=15)


def _seen(marker: Path, timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if marker.exists():
            return True
        time.sleep(0.1)
    return False


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    marker = tmp_path / "agent-ran"
    fake = home / ".local" / "bin" / "w7agent"
    fake.write_text(f"#!/bin/sh\necho ran > {marker}\nsleep 20\n")
    fake.chmod(0o755)
    monkeypatch.setenv("HOME", str(home))
    clean = [p for p in os.environ.get("PATH", "").split(os.pathsep) if not p.endswith(".local/bin")]
    monkeypatch.setenv("PATH", os.pathsep.join(clean))
    name = derive_test_socket("agent_path")
    try:
        yield marker, name
    finally:
        _tmux(name, "kill-server")


@pytest.mark.asyncio
@pytest.mark.parametrize("wrapped", [False, True])
async def test_create_launches_a_native_claude(rig, tmp_path, wrapped):
    marker, socket = rig
    backend = TmuxBackend(
        session_id=f"aip-{uuid.uuid4().hex[:6]}", working_dir=tmp_path, on_output=None, socket_name=socket)
    try:
        await backend.start(command=rc_prefixed("command w7agent") if wrapped else f"command w7agent")
        assert _seen(marker), "create: the fake agent in ~/.local/bin never ran"
    finally:
        await backend.stop()


@pytest.mark.asyncio
async def test_respawn_launches_a_native_claude_in_a_session_born_without_the_folder(rig, tmp_path):
    marker, socket = rig
    name = f"cloude_aip_{uuid.uuid4().hex[:6]}"
    _tmux(socket, "new-session", "-d", "-s", name, "-c", str(tmp_path), "-x", "80", "-y", "24")
    _tmux(socket, "set-option", "-t", name, "remain-on-exit", "on")
    _tmux(socket, "send-keys", "-t", name, "exit", "Enter")
    for _ in range(80):
        if _tmux(socket, "list-panes", "-t", name, "-F", "#{pane_dead}").stdout.strip() == "1":
            break
        await asyncio.sleep(0.1)
    else:
        pytest.skip("setup: the pane never died")
    backend = TmuxBackend.for_external(
        session_name=name, working_dir=tmp_path, on_output=None, socket_name=socket)
    result = await backend.respawn(chosen_agent_command=rc_prefixed("command w7agent"), chosen_agent_type="claude")
    assert result.ok is True, result.detail
    assert _seen(marker), "respawn: the fake agent in ~/.local/bin never ran"
