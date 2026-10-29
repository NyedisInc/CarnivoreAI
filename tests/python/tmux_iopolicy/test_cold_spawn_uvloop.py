import asyncio
import subprocess
import tempfile
from pathlib import Path

import pytest

from src.core.tmux_backend import TmuxBackend

uvloop = pytest.importorskip("uvloop")


def test_cold_new_session_returns_under_uvloop(tmux_test_socket):
    sock = tmux_test_socket
    backend = TmuxBackend("ses_uvloop0", Path(tempfile.mkdtemp()), socket_name=sock, session_name="carnivore_uvloop0")

    async def go() -> int:
        rc, _ = await asyncio.wait_for(backend._spawn_session(["new-session", "-d", "-s", "carnivore_uvloop0"], {}), 15)
        return rc

    try:
        assert uvloop.run(go()) == 0
    finally:
        subprocess.run(["tmux", "-L", sock, "kill-session", "-t", "=carnivore_uvloop0"], capture_output=True)
