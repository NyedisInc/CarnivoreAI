
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import List

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_idle_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_idle_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core import tmux_discovery
from src.core.tmux_control.reader import close_readers, control_run
from src.core.tmux_transport.run import tmux_run_text
from tests.socket_guard import derive_test_socket

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="real tmux binary not available")


def _tmux(socket: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", "-L", socket, *args], capture_output=True, check=False, timeout=15)


@pytest.fixture()
def socket(monkeypatch):
    monkeypatch.setenv("CARNIVORE_CONTROL_INPUT", "1")
    monkeypatch.delenv("CLOUDE_CONTROL_INPUT", raising=False)
    name = derive_test_socket("idlespawn")
    assert _tmux(name, "new-session", "-d", "-s", "idle", "-x", "80", "-y", "24", "cat").returncode == 0
    try:
        for _ in range(100):
            if control_run(name, ["list-sessions"]) is not None:
                break
            time.sleep(0.1)
        else:
            raise AssertionError("control client never came up")
        yield name
    finally:
        close_readers()
        tmux_discovery.reset_probe_cache()
        _tmux(name, "kill-server")


@pytest.fixture()
def spawns(monkeypatch) -> List[List[str]]:
    seen: List[List[str]] = []
    real = subprocess.Popen

    def spy(args, *a, **kw):
        seen.append([str(w) for w in (args if isinstance(args, (list, tuple)) else [args])])
        return real(args, *a, **kw)

    monkeypatch.setattr(subprocess, "Popen", spy)
    return seen


def test_server_version_over_control_equals_the_subprocess_answer(socket):
    from src.core.tmux_control.reader import control_server_version

    real = _tmux(socket, "display-message", "-p", "#{version}").stdout.decode().strip()
    assert real
    assert control_server_version(socket) == real


def test_idle_reselection_and_reads_spawn_no_tmux(socket, spawns):
    tmux_discovery.select_tmux(socket)
    tmux_discovery._selection_cache.clear()
    tmux_discovery._stable_choice[socket] = (tmux_discovery.socket_signature(socket), time.monotonic() - 10_000)
    del spawns[:]
    chosen = tmux_discovery.select_tmux(socket)
    listed = tmux_run_text(socket, "list-panes", "-a", "-F", "#{pane_id}", timeout=2.0)
    assert chosen and listed.ok and listed.stdout.strip()
    tmux = [argv for argv in spawns if "tmux" in os.path.basename(argv[0])]
    assert tmux == [], f"idle pass spawned tmux: {tmux}"
