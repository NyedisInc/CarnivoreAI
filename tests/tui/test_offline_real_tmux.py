
from __future__ import annotations

import contextlib
import fcntl
import os
import pty
import select
import shutil
import signal
import struct
import subprocess
import tempfile
import termios
import time
from pathlib import Path
from typing import Iterator

import pytest

from src.core.tmux_discovery import resolve_tmux_path
from src.tui import attach
from src.tui.offline import socket_check
from src.tui.offline.listing import list_rows
from src.tui.offline.tmux_cmd import TmuxNotRunning
from tests.socket_guard import TEST_SOCKET_NAME

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="needs tmux")


@pytest.fixture
def private_socket(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[str, Path]]:
    root = Path(os.path.realpath(tempfile.mkdtemp(prefix="off", dir="/tmp")))
    uid_dir = root / f"tmux-{os.getuid()}"
    uid_dir.mkdir(mode=0o700)
    uid_dir.chmod(0o700)
    monkeypatch.setattr(socket_check, "DEFAULT_TMPDIR", str(root))
    monkeypatch.delenv("TMUX_TMPDIR", raising=False)
    binary = resolve_tmux_path()
    assert binary
    path = uid_dir / TEST_SOCKET_NAME
    try:
        yield binary, path
    finally:
        subprocess.run([binary, "-S", str(path), "kill-server"], capture_output=True, check=False)
        shutil.rmtree(root, ignore_errors=True)


def _tmux(binary: str, path: Path, *args: str) -> str:
    return subprocess.run([binary, "-S", str(path), *args], capture_output=True, text=True, check=True).stdout.strip()


def _winsize(fd: int, rows: int, cols: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def test_lists_marks_dead_and_reports_gone(private_socket: tuple[str, Path]) -> None:
    binary, path = private_socket
    _tmux(binary, path, "-f", "/dev/null", "new-session", "-d", "-s", "carnivore_rt", "-x", "120", "-y", "40", "sleep 300")
    _tmux(binary, path, "set-option", "-g", "remain-on-exit", "on")
    _tmux(binary, path, "new-session", "-d", "-s", "carnivore_dead", "true")
    _tmux(binary, path, "new-session", "-d", "-s", "by hand", "sleep 300")
    for _ in range(50):
        if _tmux(binary, path, "display-message", "-p", "-t", "=carnivore_dead:", "#{pane_dead}") == "1":
            break
        time.sleep(0.1)

    context = socket_check.resolve_offline(TEST_SOCKET_NAME, {}, os.getuid(), binary)
    assert context.target.socket_path == str(path)
    rows = {r.tmux_name: r for r in list_rows(context.target, None, show_all=False)}
    assert set(rows) == {"carnivore_rt", "carnivore_dead"}
    assert rows["carnivore_dead"].dead and not rows["carnivore_rt"].dead
    assert "by hand" in {r.tmux_name for r in list_rows(context.target, None, show_all=True)}
    size = attach.read_pane_size(context.target.prefix(), "carnivore_rt")
    assert size is not None and (size.cols, size.rows) == (120, 40)

    subprocess.run([binary, "-S", str(path), "kill-server"], capture_output=True, check=False)
    with pytest.raises(TmuxNotRunning):
        socket_check.resolve_offline(TEST_SOCKET_NAME, {}, os.getuid(), binary)


def test_fit_resizes_the_pane_to_this_terminal(private_socket: tuple[str, Path]) -> None:
    binary, path = private_socket
    _tmux(binary, path, "-f", "/dev/null", "new-session", "-d", "-s", "carnivore_fit", "-x", "150", "-y", "50", "sleep 300")
    _tmux(binary, path, "set-option", "-g", "window-size", "manual")
    plan = attach.plan_attach("carnivore_fit", TEST_SOCKET_NAME, {"PATH": os.environ["PATH"]}, prefix=(binary, "-S", str(path)), fit=True)
    pid, fd = pty.fork()
    if pid == 0:
        _winsize(0, 20, 60)
        os.execvpe(plan.argvs[0][0], list(plan.argvs[0]), dict(plan.env, TERM="xterm"))
    _winsize(fd, 20, 60)
    size = ""
    try:
        for _ in range(50):
            time.sleep(0.1)
            if select.select([fd], [], [], 0)[0]:
                with contextlib.suppress(OSError):
                    os.read(fd, 65536)
            size = _tmux(binary, path, "display-message", "-p", "-t", "=carnivore_fit:", "#{window_width}x#{window_height}")
            if size == "60x19":
                break
        assert size == "60x19", size
    finally:
        os.kill(pid, signal.SIGTERM)
        with contextlib.suppress(ChildProcessError):
            os.waitpid(pid, 0)
