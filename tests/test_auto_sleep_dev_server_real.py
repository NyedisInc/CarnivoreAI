
from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Iterator, List

import pytest

from src.core.auto_sleep import pane_listeners
from src.core.tmux_backend import TmuxBackend
from tests.socket_guard import TEST_SOCKET_NAME
from tests.test_auto_sleep_sleeper import _add, _run, world  # noqa: F401

pytestmark = pytest.mark.skipif(
    shutil.which("tmux") is None or not Path(pane_listeners.LSOF_PATH).exists(),
    reason="needs tmux and /usr/sbin/lsof",
)

CHILD = """
import os, socket, sys, time
out, listen = sys.argv[1], sys.argv[2] == "listen"
sock = socket.socket()
sock.bind(("127.0.0.1", 0))
if listen:
    sock.listen()
with open(out + ".tmp", "w") as fh:
    fh.write("%d %d" % (os.getpid(), sock.getsockname()[1]))
os.replace(out + ".tmp", out)
time.sleep(600)
"""

PARENT = """
import subprocess, sys
subprocess.Popen([sys.executable] + sys.argv[1:]).wait()
"""


def _wait_for(path: Path) -> int:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if path.exists():
            return int(path.read_text().split()[0])
        time.sleep(0.05)
    raise AssertionError(f"the child never wrote {path}")


@pytest.fixture
def spawned(tmp_path: Path, tmux_test_socket: str) -> Iterator[dict]:
    child = tmp_path / "child.py"
    child.write_text(CHILD)
    parent = tmp_path / "parent.py"
    parent.write_text(PARENT)
    names: List[str] = []
    pids: List[int] = []

    def pane(listen: bool) -> TmuxBackend:
        name = "cloude_t946_%s" % uuid.uuid4().hex[:8]
        record = tmp_path / f"{name}.rec"
        argv = [sys.executable, str(parent), str(child), str(record),
                "listen" if listen else "quiet"]
        subprocess.run(
            ["tmux", "-L", TEST_SOCKET_NAME, "new-session", "-d", "-s", name,
             " ".join(shlex.quote(a) for a in argv)],
            check=True, capture_output=True, timeout=10,
        )
        names.append(name)
        pids.append(_wait_for(record))
        return TmuxBackend.for_external(
            session_name=name, working_dir=tmp_path, on_output=None,
            socket_name=TEST_SOCKET_NAME,
        )

    def loose(listen: bool) -> int:
        record = tmp_path / f"loose-{uuid.uuid4().hex[:8]}.rec"
        proc = subprocess.Popen([sys.executable, str(child), str(record),
                                 "listen" if listen else "quiet"])
        pids.append(proc.pid)
        return _wait_for(record)

    try:
        yield {"pane": pane, "loose": loose}
    finally:
        for name in names:
            subprocess.run(["tmux", "-L", TEST_SOCKET_NAME, "kill-session", "-t", "=" + name],
                           capture_output=True, check=False, timeout=10)
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def _serve_from(world, backend: TmuxBackend) -> None:  # noqa: F811
    world.manager._registry.backends["ses_1"] = backend
    world.sleeper._take_listeners = pane_listeners.take_snapshot


def test_a_listening_child_of_the_pane_keeps_it_awake(world, spawned):  # noqa: F811
    _add(world)
    backend = spawned["pane"](listen=True)
    _serve_from(world, backend)
    pane_pid = backend.pid
    assert pane_pid is not None
    snapshot = pane_listeners.take_snapshot()
    assert snapshot.pane_listeners(pane_pid), "the real lsof did not see the pane's listener"
    assert _run(world) == []
    assert world.calls == []


def test_a_quiet_child_of_the_pane_does_not_keep_it_awake(world, spawned):  # noqa: F811
    _add(world)
    _serve_from(world, spawned["pane"](listen=False))
    assert _run(world) == ["row-uuid-1"]


def test_a_listener_outside_the_pane_does_not_keep_it_awake(world, spawned):  # noqa: F811
    _add(world)
    outside = spawned["loose"](listen=True)
    backend = spawned["pane"](listen=False)
    _serve_from(world, backend)
    assert outside in pane_listeners.take_snapshot().listeners
    assert _run(world) == ["row-uuid-1"]
