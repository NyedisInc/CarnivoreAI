
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from src.core.session_move.apply import pane_folder
from src.core.tmux_backend import TmuxBackend
from tests.socket_guard import derive_test_socket

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="real tmux binary not available")


def _tmux(socket: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", "-L", socket, *args], capture_output=True, text=True, check=False, timeout=15)


def _read(socket: str, name: str, fmt: str) -> str:
    return _tmux(socket, "display-message", "-p", "-t", f"={name}:", fmt).stdout.strip()


def _wait_for(socket: str, name: str, fmt: str, want: str, timeout: float = 6.0) -> str:
    deadline, value = time.monotonic() + timeout, ""
    while time.monotonic() < deadline:
        value = _read(socket, name, fmt)
        if value == want:
            return value
        time.sleep(0.1)
    return value


@pytest.fixture()
def socket(request: pytest.FixtureRequest) -> str:
    name = derive_test_socket(f"mv_{request.node.name[:20]}")
    _tmux(name, "new-session", "-d", "-s", "keeper", "-x", "80", "-y", "24")
    _tmux(name, "set-option", "-wg", "remain-on-exit", "on")
    yield name
    subprocess.run(["tmux", "-L", name, "kill-server"], capture_output=True, check=False)


def _dead_session(socket: str, name: str, folder: Path) -> str:
    _tmux(socket, "new-session", "-d", "-s", name, "-c", str(folder), "-x", "80", "-y", "24", 'sh -c "exit 0"')
    assert _wait_for(socket, name, "#{pane_dead}", "1") == "1"
    return _read(socket, name, "#{session_created}")


@pytest.mark.parametrize("move", [True, False], ids=["with_start_directory", "control_without"])
def test_respawn_with_a_start_directory_lands_in_the_new_folder_in_the_same_session(
        socket: str, tmp_path: Path, move: bool) -> None:
    old, new = (tmp_path / "ses_ab12").resolve(), (tmp_path / "app").resolve()
    old.mkdir()
    new.mkdir()
    epoch = _dead_session(socket, "mv", old)
    backend = TmuxBackend.for_external(session_name="mv", working_dir=old, on_output=None, socket_name=socket)
    result = asyncio.run(backend.respawn(agent_command='sh -c "sleep 60"',
                                         **({"start_directory": str(new)} if move else {})))
    assert result.ok, result.detail
    assert _wait_for(socket, "mv", "#{pane_dead}", "0") == "0"
    assert _read(socket, "mv", "#{session_created}") == epoch
    measured = pane_folder("mv", socket)
    assert measured == (str(new) if move else str(old))
    assert os.path.realpath(_read(socket, "mv", "#{pane_start_path}")) == (str(new) if move else str(old))


def test_a_folder_name_holding_tmux_format_characters_is_taken_literally(socket: str, tmp_path: Path) -> None:
    old = (tmp_path / "ses_ab12").resolve()
    old.mkdir()
    new = (tmp_path / "x#{session_name}#(touch ran)y").resolve()
    new.mkdir()
    _dead_session(socket, "mvfmt", old)
    backend = TmuxBackend.for_external(session_name="mvfmt", working_dir=old, on_output=None, socket_name=socket)
    result = asyncio.run(backend.respawn(agent_command='sh -c "sleep 60"', start_directory=str(new)))
    assert result.ok, result.detail
    assert _wait_for(socket, "mvfmt", "#{pane_dead}", "0") == "0"
    assert pane_folder("mvfmt", socket) == str(new)
    assert not (Path.home() / "ran").exists() and not (tmp_path / "ran").exists()
