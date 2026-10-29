
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from src.core.tmux_backend import TmuxBackend
from tests.socket_guard import derive_test_socket

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="real tmux binary not available")

HOSTILE = 'x#{session_name}#(touch "$PROOF")y'


def _tmux(socket: str, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", "-L", socket, *args], capture_output=True, text=True, check=False, timeout=15, env=env)


def _wait_for(socket: str, name: str, fmt: str, want: str, timeout: float = 6.0) -> str:
    deadline, value = time.monotonic() + timeout, ""
    while time.monotonic() < deadline:
        value = _tmux(socket, "display-message", "-p", "-t", f"={name}:", fmt).stdout.strip()
        if value == want:
            break
        time.sleep(0.1)
    return value


@pytest.fixture()
def world(request: pytest.FixtureRequest, tmp_path: Path):
    socket = derive_test_socket(f"sd_{request.node.name[:20]}")
    proof = tmp_path / "proof"
    folder = (tmp_path / HOSTILE)
    folder.mkdir()
    started = _tmux(socket, "new-session", "-d", "-s", "keeper", "-x", "80", "-y", "24", "sleep 120",
                    env={**os.environ, "PROOF": str(proof)})
    assert started.returncode == 0, started.stderr
    _tmux(socket, "set-option", "-wg", "remain-on-exit", "on")
    yield socket, proof, folder.resolve()
    subprocess.run(["tmux", "-L", socket, "kill-server"], capture_output=True, check=False)


def _pane_folder(socket: str, name: str) -> str:
    return os.path.realpath(_tmux(socket, "display-message", "-p", "-t", f"={name}:", "#{pane_current_path}").stdout.strip())


@pytest.mark.parametrize("verb", ["new-session", "respawn-pane"])
def test_the_control_an_unescaped_c_loses_the_folder(world, verb: str) -> None:
    socket, proof, folder = world
    if verb == "new-session":
        _tmux(socket, "new-session", "-d", "-s", "raw", "-c", str(folder), "sleep 60")
    else:
        _tmux(socket, "new-session", "-d", "-s", "raw", 'sh -c "exit 0"')
        assert _wait_for(socket, "raw", "#{pane_dead}", "1") == "1"
        _tmux(socket, "respawn-pane", "-c", str(folder), "-t", "=raw:", "sleep 60")
    assert _wait_for(socket, "raw", "#{pane_dead}", "0") == "0"
    time.sleep(0.5)
    assert _pane_folder(socket, "raw") != str(folder)


def test_new_session_c_takes_a_hostile_folder_literally(world, tmp_path: Path) -> None:
    socket, proof, folder = world
    backend = TmuxBackend.for_external(session_name="sdnew", working_dir=folder, on_output=None, socket_name=socket)
    asyncio.run(backend.start(command="sleep 60"))
    assert _wait_for(socket, "sdnew", "#{pane_dead}", "0") == "0"
    time.sleep(0.5)
    assert _pane_folder(socket, "sdnew") == str(folder)
    assert not proof.exists()


def test_respawn_pane_c_takes_a_hostile_folder_literally(world) -> None:
    socket, proof, folder = world
    _tmux(socket, "new-session", "-d", "-s", "sdre", "-x", "80", "-y", "24", 'sh -c "exit 0"')
    assert _wait_for(socket, "sdre", "#{pane_dead}", "1") == "1"
    backend = TmuxBackend.for_external(session_name="sdre", working_dir=Path(tmp_dir()), on_output=None, socket_name=socket)
    result = asyncio.run(backend.respawn(agent_command='sh -c "sleep 60"', start_directory=str(folder)))
    assert result.ok, result.detail
    assert _wait_for(socket, "sdre", "#{pane_dead}", "0") == "0"
    time.sleep(0.5)
    assert _pane_folder(socket, "sdre") == str(folder)
    assert not proof.exists()


def tmp_dir() -> str:
    return os.path.realpath(os.environ.get("TMPDIR", "/tmp"))
