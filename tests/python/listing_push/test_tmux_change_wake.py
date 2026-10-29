
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_t9_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_t9_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.listing_push.publisher import Collection, CollectionResult, ListingPublisher
from src.core.tmux_control import changes
from src.core.tmux_control.client import get_control_input, shutdown_all
from tests.socket_guard import derive_test_socket

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="real tmux binary not available")


def _tmux(socket: str, *args: str) -> None:
    subprocess.run(["tmux", "-L", socket, *args], capture_output=True, check=False, timeout=15)


@pytest.mark.asyncio
async def test_new_session_by_hand_wakes_a_pass_and_idle_does_not(monkeypatch):
    monkeypatch.setenv("CARNIVORE_CONTROL_INPUT", "1")
    socket = derive_test_socket("t9wake")
    _tmux(socket, "new-session", "-d", "-s", "seed", "sleep 60")
    built = []

    async def build(_ctx):
        built.append(1)
        return CollectionResult(rows=[])

    publisher = ListingPublisher(
        [Collection("c", build, lambda r: r.get("name"))], lambda frame: 0, lambda: 1,
        backstop_seconds=60.0, min_interval=0.05, feed=changes.control_feed(lambda: socket))
    changes.add_listener(lambda sock: publisher.wake() if sock == socket else None)
    loop_task = asyncio.create_task(publisher.run())
    try:
        assert await get_control_input(socket).listen()
        await asyncio.sleep(1.0)
        baseline = len(built)
        await asyncio.sleep(1.5)
        assert len(built) == baseline, "idle socket must cause no pass"
        _tmux(socket, "new-session", "-d", "-s", "byhand", "sleep 60")
        await asyncio.sleep(changes.DEBOUNCE_SECONDS + 0.8)
        assert len(built) == baseline + 1, "a session made by hand must cause exactly one pass inside the window"
    finally:
        loop_task.cancel()
        await shutdown_all()
        _tmux(socket, "kill-server")
