
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import List, Optional, Tuple

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ctllate_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ctllate_logs_"))

# ruff: noqa: E402
from src.core.tmux_control import reader as reader_mod
from src.core.tmux_control.reader import close_readers, control_run
from tests.socket_guard import derive_test_socket

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="real tmux binary not available")

BIG = ["capture-pane", "-p", "-J", "-S", "-", "-t", "=big:"]
QUICK = [["list-panes", "-a", "-F", "#{session_name} #{pane_pid}"], ["has-session", "-t", "=big"],
         ["show-options", "-gv", "history-limit"], ["capture-pane", "-p", "-t", "=big:"]]


def _tmux(socket: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", "-L", socket, *args], capture_output=True, check=False, timeout=30)


@pytest.fixture()
def socket(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CARNIVORE_CONTROL_INPUT", "1")
    monkeypatch.delenv("CLOUDE_CONTROL_INPUT", raising=False)
    name = derive_test_socket("ctllate")
    fill = f"{sys.executable} -c \"import sys; sys.stdout.write(('x' * 100 + chr(10)) * 40000)\"; exec cat"
    assert _tmux(name, "-f", "/dev/null", "new-session", "-d", "-s", "holder", "cat").returncode == 0
    assert _tmux(name, "set", "-g", "history-limit", "100000").returncode == 0
    assert _tmux(name, "new-session", "-d", "-s", "big", "-x", "120", "-y", "24", "sh", "-c", fill).returncode == 0
    for _ in range(100):
        size = _tmux(name, "display-message", "-p", "-t", "=big:", "#{history_size}").stdout.strip()
        if size.isdigit() and int(size) > 30000:
            break
        time.sleep(0.1)
    else:
        raise AssertionError("the big pane's history never filled")
    try:
        yield name
    finally:
        close_readers()
        _tmux(name, "kill-server")


def _up(socket: str) -> reader_mod.ControlReader:
    for _ in range(100):
        if control_run(socket, ["list-sessions"]) is not None:
            return reader_mod._READERS[socket]
        time.sleep(0.1)
    raise AssertionError("client never came up")


def test_a_late_reply_keeps_the_client_and_concurrent_readers_still_answer(socket, monkeypatch):
    reader = _up(socket)
    proc = reader._proc
    assert proc is not None
    budget = reader_mod.LOOP_TIMEOUT_SECONDS
    monkeypatch.setattr(reader_mod, "LOOP_TIMEOUT_SECONDS", 0.0)
    assert reader.query(BIG) is None
    monkeypatch.setattr(reader_mod, "LOOP_TIMEOUT_SECONDS", budget)
    assert reader._proc is proc
    t0 = time.monotonic()
    assert reader.query(QUICK[0]) is None or reader._late is None
    assert time.monotonic() - t0 < 0.1

    answers: List[Tuple[Tuple[str, ...], Optional[tuple]]] = []
    guard = threading.Lock()

    def ask(commands: List[List[str]], seconds: float) -> None:
        end, i = time.monotonic() + seconds, 0
        while time.monotonic() < end:
            args = commands[i % len(commands)]
            got = reader.query(args)
            with guard:
                answers.append((tuple(args), got))
            i += 1
            time.sleep(0.01)

    workers = [threading.Thread(target=ask, args=(QUICK, 2.0)) for _ in range(6)]
    workers.append(threading.Thread(target=ask, args=([BIG], 2.0)))
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(60)
    assert not any(w.is_alive() for w in workers)

    assert reader._proc is proc and proc.poll() is None
    for _ in range(50):
        if reader.query(["list-sessions"]) is not None and reader._late is None:
            break
        time.sleep(0.1)
    assert reader._late is None and reader._proc is proc
    truth = {args: (lambda d: (d.returncode, d.stdout, d.stderr))(_tmux(socket, *args)) for args, _ in answers}
    answered = [(args, got) for args, got in answers if got is not None]
    assert {args for args, _ in answered} >= {tuple(q) for q in QUICK}
    assert all(got == truth[args] for args, got in answered)
