
from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
from pathlib import Path
from typing import Iterator

import pytest

from src.core.tmux_backend import TmuxBackend
from src.core.tmux_transport.target import exact_pane_target, exact_session_target
from tests.socket_guard import derive_test_socket

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="real tmux binary not available")


def _tmux(socket: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", "-L", socket, "-f", "/dev/null", *args], capture_output=True,
                          text=True, check=False)


@pytest.fixture()
def socket_with_abc() -> Iterator[str]:
    socket = derive_test_socket("exact_targets")
    assert _tmux(socket, "new-session", "-d", "-s", "abc", "-x", "80", "-y", "24", "cat").returncode == 0
    try:
        yield socket
    finally:
        _tmux(socket, "kill-server")


def _ghost(socket: str, tmp_path: Path) -> TmuxBackend:
    return TmuxBackend.for_external(session_name="ab", working_dir=tmp_path, on_output=None,
                                    socket_name=socket)


def test_builders_are_exact() -> None:
    assert exact_pane_target("ab") == "=ab:"
    assert exact_session_target("ab") == "=ab"
    for bad in ("a:b", "a.b"):
        with pytest.raises(ValueError):
            exact_pane_target(bad)


def test_write_to_a_gone_prefix_session_types_nothing_into_the_longer_one(
    socket_with_abc: str, tmp_path: Path,
) -> None:
    backend = _ghost(socket_with_abc, tmp_path)
    try:
        asyncio.run(backend.write(b"LEAKED_KEYS"))
    except (RuntimeError, OSError):
        pass
    time.sleep(0.3)
    shown = _tmux(socket_with_abc, "capture-pane", "-p", "-t", "=abc:").stdout
    assert "LEAKED_KEYS" not in shown


def test_reads_of_a_gone_prefix_session_do_not_answer_with_the_longer_ones(
    socket_with_abc: str, tmp_path: Path,
) -> None:
    backend = _ghost(socket_with_abc, tmp_path)
    abc_pid = _tmux(socket_with_abc, "display-message", "-p", "-t", "=abc:", "#{pane_pid}").stdout.strip()
    assert abc_pid.isdigit()
    assert backend.pid != int(abc_pid)
    assert backend.pane_cursor_position() is None
    assert backend.capture_visible_screen() == b""


def test_resize_of_a_gone_prefix_session_leaves_the_longer_one_alone(
    socket_with_abc: str, tmp_path: Path,
) -> None:
    backend = _ghost(socket_with_abc, tmp_path)
    backend.resize(100, 30)
    size = _tmux(socket_with_abc, "display-message", "-p", "-t", "=abc:", "#{window_width}x#{window_height}")
    assert size.stdout.strip() == "80x24"


def test_stop_of_a_gone_prefix_session_keeps_the_longer_one_alive(
    socket_with_abc: str, tmp_path: Path,
) -> None:
    backend = _ghost(socket_with_abc, tmp_path)
    asyncio.run(backend.stop())
    assert _tmux(socket_with_abc, "has-session", "-t", "=abc").returncode == 0
