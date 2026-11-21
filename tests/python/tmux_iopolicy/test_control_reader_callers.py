
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ctlcall_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ctlcall_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.tmux_control.reader import close_readers, control_run
from src.core.tmux_discovery import tmux_argv_prefix
from src.core.tmux_transport.run import tmux_argv_stdout
from tests.socket_guard import derive_test_socket

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="real tmux binary not available")


def _tmux(socket: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", "-L", socket, *args], capture_output=True, check=False, timeout=15)


@pytest.fixture()
def socket(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CARNIVORE_CONTROL_INPUT", "1")
    monkeypatch.delenv("CLOUDE_CONTROL_INPUT", raising=False)
    name = derive_test_socket("ctlcall")
    assert _tmux(name, "new-session", "-d", "-s", "known", "-x", "80", "-y", "24", "cat").returncode == 0
    time.sleep(0.3)
    try:
        yield name
    finally:
        close_readers()
        _tmux(name, "kill-server")


def _callers(socket: str) -> Dict[str, Callable[[], Any]]:
    from src.core.account_switch import auto_restart
    from src.core.attention import codex_pane_home
    from src.core.attention.screen_read import capture_screen
    from src.core.session_pane_facts import read_pane_facts

    prefix = tmux_argv_prefix(socket)
    return {
        "capture_screen": lambda: capture_screen(socket, "nosuch"),
        "codex_home_gone": lambda: codex_pane_home._read_variable(socket, ["show-environment", "-t", "=nosuch", "CODEX_HOME"]),
        "codex_home_unset": lambda: codex_pane_home._read_variable(socket, ["show-environment", "-t", "=known", "CODEX_HOME"]),
        "argv_stdout": lambda: tmux_argv_stdout(prefix + ["list-panes", "-t", "=nosuch:", "-F", "#{pane_pid}"]),
        "auto_restart": lambda: asyncio.run(auto_restart._tmux_output(socket, "show-options", "-pv", "-t", "=nosuch:", "@x")),
        "pane_facts": lambda: asyncio.run(read_pane_facts(socket, "nosuch")),
    }


def test_a_gone_session_answers_like_the_subprocess_with_no_spawn(socket, monkeypatch):
    monkeypatch.setenv("CARNIVORE_CONTROL_INPUT", "0")
    truth = {name: call() for name, call in _callers(socket).items()}
    monkeypatch.setenv("CARNIVORE_CONTROL_INPUT", "1")
    assert truth["codex_home_unset"] == (None, True)
    for _ in range(100):
        if control_run(socket, ["list-sessions"]) is not None:
            break
        time.sleep(0.1)
    spawns: List[List[str]] = []
    real_run, real_popen, real_exec = subprocess.run, subprocess.Popen, asyncio.create_subprocess_exec

    def note(argv: Any) -> None:
        words = [str(w) for w in argv]
        if socket in words:
            spawns.append(words)

    monkeypatch.setattr(subprocess, "run", lambda argv, *a, **k: note(argv) or real_run(argv, *a, **k))
    monkeypatch.setattr(subprocess, "Popen", lambda argv, *a, **k: note(argv) or real_popen(argv, *a, **k))

    async def exec_(*argv: Any, **k: Any) -> Any:
        note(argv)
        return await real_exec(*argv, **k)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", exec_)
    got = {name: call() for name, call in _callers(socket).items()}
    assert got == truth
    spawning = {w[3] if len(w) > 3 else "?" for w in spawns}
    assert spawning <= {"display-message"}, spawns
