from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
import time

import pytest

from src.core.auto_sleep import pane_ports
from src.core.auto_sleep.pane_ports import PortWatch, keep_listener, read_tree_listeners
from src.core.conversation_writers import MeasureError

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="libproc is macOS only")

_SERVER = (
    "import socket,sys,time\n"
    "s=socket.socket(); s.bind(('127.0.0.1',0)); s.listen(); print(s.getsockname()[1], flush=True)\n"
    "w=socket.socket(); w.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); w.bind(('0.0.0.0',0)); w.listen(); print(w.getsockname()[1], flush=True)\n"
    "time.sleep(60)\n"
)


@pytest.fixture
def pane_with_server():
    shell = subprocess.Popen(["/bin/sh", "-c", f'"{sys.executable}" -c "$0"; exit $?', _SERVER],
                             stdout=subprocess.PIPE, text=True)
    try:
        loop_port = int(shell.stdout.readline())
        any_port = int(shell.stdout.readline())
        yield shell.pid, loop_port, any_port
    finally:
        subprocess.run(["/usr/bin/pkill", "-P", str(shell.pid)], check=False)
        shell.kill()
        shell.wait()


def test_libproc_finds_the_childs_listeners_and_filters(pane_with_server):
    pane, loop_port, any_port = pane_with_server
    entries = read_tree_listeners([pane])[pane]
    assert {port: address for port, address, _ in entries} == {loop_port: "127.0.0.1", any_port: "0.0.0.0"}
    assert all((name or "").lower().startswith("python") for _, _, name in entries)
    server = int(subprocess.run(["/usr/bin/pgrep", "-P", str(pane)], capture_output=True, text=True).stdout.split()[0])
    assert read_tree_listeners([server])[server] == []
    assert keep_listener((22, "0.0.0.0")) is False
    assert keep_listener((5173, "10.0.0.6")) is False
    assert keep_listener((5173, "::1")) and keep_listener((5173, "::"))


def test_zero_reads_until_watched_then_ttl_failure_keeps_last_good():
    calls = []
    answers = [{7: [(5173, "127.0.0.1")]}, MeasureError("boom")]

    def read(panes):
        calls.append(set(panes))
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a

    now = [100.0]
    watch = PortWatch(read=read, ttl=15, clock=lambda: now[0])
    wakes = []

    async def run():
        for _ in range(5):
            assert watch.servers(7) == []
        assert calls == []
        watch.tick(lambda: wakes.append(1))
        await watch._task
        first = watch.servers(7)
        assert [s.port for s in first] == [5173] and wakes == [1]
        watch.tick(lambda: wakes.append(1))
        assert len(calls) == 1
        now[0] += 16
        watch.tick(lambda: wakes.append(1))
        await watch._task
        assert len(calls) == 2 and wakes == [1]
        assert watch.servers(7) == first

    asyncio.run(run())


def test_unchanged_ports_keep_their_record_so_the_listing_does_not_churn():
    watch = PortWatch(read=lambda p: {}, ttl=0)
    assert watch.commit({1}, {1: [(3000, "127.0.0.1")]}) is True
    rec = watch.servers(1)[0]
    time.sleep(0.01)
    assert watch.commit({1}, {1: [(3000, "127.0.0.1")]}) is False
    assert watch.servers(1)[0] is rec
    assert watch.commit({1}, {1: []}) is True and watch.servers(1) == []
