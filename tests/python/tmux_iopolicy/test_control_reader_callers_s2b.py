
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ctl2b_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ctl2b_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.tmux_control.names import is_control_input_session
from src.core.tmux_control.reader import close_readers, control_run
from tests.socket_guard import derive_test_socket

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="real tmux binary not available")

KNOWN, GONE = "known", "nosuch"


def _tmux(socket: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", "-L", socket, *args], capture_output=True, check=False, timeout=15)


@pytest.fixture()
def socket(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("CARNIVORE_CONTROL_INPUT", "1")
    monkeypatch.delenv("CLOUDE_CONTROL_INPUT", raising=False)
    name = derive_test_socket("ctl2b")
    started = _tmux(name, "new-session", "-d", "-s", KNOWN, "-c", str(tmp_path), "-x", "80", "-y", "24", "cat")
    assert started.returncode == 0
    time.sleep(0.3)
    try:
        yield name
    finally:
        close_readers()
        _tmux(name, "kill-server")


def _outcome(call: Callable[[], Any]) -> Any:
    try:
        return call()
    except Exception as exc:  # noqa: BLE001
        return type(exc).__name__


def _user_rows(names: Any) -> Any:
    return sorted(n for n in names if not is_control_input_session(n))


def _callers(socket: str, name: str) -> Dict[str, Callable[[], Any]]:
    from src.core import server_status
    from src.core.auto_sleep.port_owner import pane_pid_sessions
    from src.core.background_work.tree import probe_pane_pids
    from src.core.pack.jobs.agent_host import AgentDeps
    from src.core.pipe_prune.gather import read_panes
    from src.core.session_manager import SessionManager
    from src.core.tmux_session_cwd import probe_session_format
    from src.core.warroom.screens import capture_screen

    manager = SimpleNamespace(tmux_socket_name=lambda: socket)
    present = AgentDeps.from_app(SimpleNamespace(state=SimpleNamespace(session_manager=manager))).present

    def status() -> Any:
        got = server_status.collect_tmux(socket)
        return got["server_running"], got["history_limit"], _user_rows(row["name"] for row in got["sessions"])

    def screen() -> Any:
        got = asyncio.run(capture_screen(socket, name))
        return got.state, got.cols, got.rows

    return {
        "cwd_probe": lambda: probe_session_format(name, socket=socket, fmt="#{session_path}"),
        "adopt_cwd": lambda: str(asyncio.run(SessionManager._resolve_external_cwd(manager, name))),  # type: ignore[arg-type]
        "agent_present": lambda: asyncio.run(present(name)),
        "pane_tree": lambda: len(probe_pane_pids(name, socket)),
        "warroom_screen": screen,
        "server_status": status,
        "pipe_prune": lambda: (lambda f: (f.complete, _user_rows(f.session_names)))(read_panes(socket)),
        "port_owner": lambda: _user_rows(pane_pid_sessions(socket).values()),
    }


def _spawns_while(socket: str, monkeypatch: pytest.MonkeyPatch, calls: Dict[str, Callable[[], Any]]):
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
    try:
        return {key: _outcome(call) for key, call in calls.items()}, spawns
    finally:
        monkeypatch.setattr(subprocess, "run", real_run)
        monkeypatch.setattr(subprocess, "Popen", real_popen)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", real_exec)


@pytest.mark.parametrize("name", [KNOWN, GONE])
def test_each_caller_answers_like_the_subprocess_with_no_spawn(socket, monkeypatch, name):
    monkeypatch.setenv("CARNIVORE_CONTROL_INPUT", "0")
    truth = {key: _outcome(call) for key, call in _callers(socket, name).items()}
    monkeypatch.setenv("CARNIVORE_CONTROL_INPUT", "1")
    if name == GONE:
        assert truth["agent_present"] is False and truth["pane_tree"] == "PaneNotFound" and truth["cwd_probe"] is None
    else:
        assert truth["agent_present"] is True and truth["pane_tree"] == 1 and truth["cwd_probe"]
    for _ in range(100):
        if control_run(socket, ["list-sessions"]) is not None:
            break
        time.sleep(0.1)
    got, spawns = _spawns_while(socket, monkeypatch, _callers(socket, name))
    assert got == truth
    allowed = {"display-message"} if name == GONE else set()
    assert {w[3] if len(w) > 3 else "?" for w in spawns} <= allowed, spawns


def test_a_killed_server_answers_like_the_subprocess_and_is_never_restarted(socket, monkeypatch):
    for _ in range(100):
        if control_run(socket, ["list-sessions"]) is not None:
            break
        time.sleep(0.1)
    assert _tmux(socket, "kill-server").returncode == 0
    got = {key: _outcome(call) for key, call in _callers(socket, KNOWN).items()}
    monkeypatch.setenv("CARNIVORE_CONTROL_INPUT", "0")
    truth = {key: _outcome(call) for key, call in _callers(socket, KNOWN).items()}
    assert truth["agent_present"] is False and truth["pane_tree"] == "PaneNotFound"
    assert truth["server_status"] == (False, None, [])
    assert got == truth
    time.sleep(0.5)
    assert _tmux(socket, "list-sessions").returncode != 0
