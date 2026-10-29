
import os
import signal
import subprocess
import sys
import time

import pytest

from src.core import libproc_snapshot

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="libproc is macOS only")


def _ps_rows():
    out = subprocess.run(["/bin/ps", "-A", "-ww", "-o", "pid=,ppid=,lstart=,command="],
                         capture_output=True, text=True, check=True).stdout.splitlines()
    for line in out:
        parts = line.split(None, 7)
        if parts[0].isdigit() and len(parts) >= 7:
            yield line, parts


def test_snapshot_matches_ps_for_pid_ppid_start_and_own_argv():
    before = {r.pid: r for r in libproc_snapshot.snapshot()}
    rows = list(_ps_rows())
    after = {r.pid: r for r in libproc_snapshot.snapshot()}
    compared = 0
    for line, parts in rows:
        pid = int(parts[0])
        row = before.get(pid)
        if row is None or after.get(pid) != row or (len(parts) > 7 and parts[7].startswith("(")):
            continue
        compared += 1
        assert row.ppid == int(parts[1]), line
        assert row.lstart.split() == parts[2:7], line
        if row.uid == os.getuid() and len(parts) > 7 and "\n" not in row.command:
            assert row.command.split() == parts[7].split(), line
    assert compared > 20
    me = before[os.getpid()]
    started = libproc_snapshot.start_text([os.getpid(), 1, 2 ** 22 + 1])
    assert sorted(started) == [1, os.getpid()] and started[os.getpid()].split() == me.lstart.split()
    assert {r.pid for r in libproc_snapshot.task_table()} >= {os.getpid(), os.getppid()}


@pytest.mark.parametrize("target", [["/bin/sleep", "31.5"], None])
def test_exec_refreshes_cached_argv(target):
    argv = target or [sys.executable, "-c", "import time; time.sleep(31.5)"]
    rd, wr = os.pipe()
    child = os.fork()
    if child == 0:
        os.read(rd, 1)
        os.execv(argv[0], argv)
    try:
        row = next(r for r in libproc_snapshot.snapshot() if r.pid == child)
        assert argv[-1] not in row.command
        os.write(wr, b"x")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            row = next(r for r in libproc_snapshot.snapshot() if r.pid == child)
            if argv[-1] in row.command:
                break
            time.sleep(0.05)
        assert argv[-1] in row.command
    finally:
        os.kill(child, signal.SIGKILL)
        os.waitpid(child, 0)


def test_same_binary_exec_of_an_old_cached_process_is_picked_up(monkeypatch):
    monkeypatch.setattr(libproc_snapshot, "_YOUNG_SECONDS", 0.0)
    rd, wr = os.pipe()
    child = os.fork()
    if child == 0:
        os.read(rd, 1)
        os.execv(sys.executable, [sys.executable, "-c", "import time; time.sleep(31.5)"])
    try:
        assert "31.5" not in next(r for r in libproc_snapshot.snapshot() if r.pid == child).command
        assert "31.5" not in next(r for r in libproc_snapshot.snapshot() if r.pid == child).command
        os.write(wr, b"x")
        time.sleep(0.5)
        assert "31.5" not in next(r for r in libproc_snapshot.snapshot() if r.pid == child).command
        monkeypatch.setattr(libproc_snapshot, "_ARGV_RECHECK_SECONDS", -10.0)
        assert "31.5" in next(r for r in libproc_snapshot.snapshot() if r.pid == child).command
    finally:
        os.kill(child, signal.SIGKILL)
        os.waitpid(child, 0)


def test_empty_table_is_none_not_empty_list(monkeypatch):
    lib = libproc_snapshot._load()
    monkeypatch.setattr(lib, "proc_listallpids", lambda *a: 0, raising=False)
    assert libproc_snapshot.snapshot() is None
