
from __future__ import annotations

import shutil
import subprocess
from typing import Iterator
from unittest.mock import patch

import pytest

from src.core import tmux_session_pane_pid as module
from src.core.tmux_session_pane_pid import make_pane_pid_probe, probe_session_pane_pid
from tests.socket_guard import derive_test_socket

needs_tmux = pytest.mark.skipif(shutil.which("tmux") is None, reason="real tmux binary not available")


def _tmux(socket: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", "-L", socket, "-f", "/dev/null", *args], capture_output=True,
                          text=True, check=False)


@pytest.fixture()
def socket_with_abc() -> Iterator[str]:
    socket = derive_test_socket("pane_pid")
    assert _tmux(socket, "new-session", "-d", "-s", "abc", "-x", "80", "-y", "24", "cat").returncode == 0
    try:
        yield socket
    finally:
        _tmux(socket, "kill-server")


@needs_tmux
def test_probe_returns_the_exact_sessions_pane_pid(socket_with_abc: str) -> None:
    want = _tmux(socket_with_abc, "display-message", "-p", "-t", "=abc:", "#{pane_pid}").stdout.strip()
    assert probe_session_pane_pid("abc", socket=socket_with_abc) == int(want)


@needs_tmux
def test_probe_of_a_prefix_of_a_live_session_is_unknown_not_the_longer_ones_pid(socket_with_abc: str) -> None:
    assert probe_session_pane_pid("ab", socket=socket_with_abc) is None


def test_probe_rejects_unsafe_names_without_raising() -> None:
    assert probe_session_pane_pid("evil:target", socket="cloude") is None
    assert probe_session_pane_pid("", socket="cloude") is None


def test_probe_is_bounded_and_a_timeout_is_unknown() -> None:
    seen: dict = {}

    def wedged(*args, **kwargs):
        seen.update(kwargs)
        raise subprocess.TimeoutExpired(cmd="tmux", timeout=kwargs["timeout"])

    with patch("src.core.tmux_session_cwd.subprocess.run", wedged), \
            patch("src.core.tmux_session_cwd.shutil.which", return_value="/usr/bin/tmux"), \
            patch("src.core.tmux_session_cwd.tmux_argv_prefix", return_value=["tmux", "-L", "x"]):
        assert probe_session_pane_pid("a", socket="x", timeout=1.5) is None
    assert seen["timeout"] == 1.5


def test_probe_builds_no_throwaway_backend() -> None:
    assert not hasattr(module, "TmuxBackend")
    assert "TmuxBackend" not in open(module.__file__).read().split('"""')[2]


def test_probe_refuses_a_non_numeric_answer() -> None:
    with patch("src.core.tmux_session_pane_pid.probe_session_format", return_value="not-a-pid"):
        assert probe_session_pane_pid("a", socket="x") is None
    with patch("src.core.tmux_session_pane_pid.probe_session_format", return_value="0"):
        assert probe_session_pane_pid("a", socket="x") is None


def test_make_pane_pid_probe_binds_the_socket() -> None:
    with patch("src.core.tmux_session_pane_pid.probe_session_format", return_value="4242") as fake:
        assert make_pane_pid_probe("cloude")("a") == 4242
    assert fake.call_args.kwargs["socket"] == "cloude"
