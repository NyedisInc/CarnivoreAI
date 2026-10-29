
from __future__ import annotations

import os
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.core import local_servers as ls_module
from src.core.auto_sleep import port_owner
from src.core.auto_sleep.port_owner import find_port_owner, owner_of_listeners
from src.core.conversation_writers import Proc, ProcessTable
from src.core.local_servers import LocalServersTracker
from src.core.tmux_discovery import resolve_tmux_path
from src.utils.patterns import PatternMatch
from tests.socket_guard import TEST_SOCKET_NAME


def _table(*rows: tuple) -> ProcessTable:
    return ProcessTable.from_rows([Proc(p, pp, "x", f"cmd{p}") for p, pp in rows])


def test_owner_is_the_pane_whose_tree_holds_the_listener():
    table = _table((1, 0), (10, 1), (11, 10), (20, 1), (21, 20))
    assert owner_of_listeners(frozenset({11}), {10: "a", 20: "b"}, table) == "a"
    assert owner_of_listeners(frozenset({21}), {10: "a", 20: "b"}, table) == "b"


def test_listener_that_is_the_pane_pid_itself_is_owned():
    assert owner_of_listeners(frozenset({10}), {10: "a"}, _table((1, 0), (10, 1))) == "a"


def test_listener_outside_every_pane_has_no_owner():
    table = _table((1, 0), (10, 1), (30, 1))
    assert owner_of_listeners(frozenset({30}), {10: "a"}, table) is None


def test_parent_cycle_terminates():
    table = _table((5, 6), (6, 5))
    assert owner_of_listeners(frozenset({5}), {10: "a"}, table) is None


def test_pane_pid_sessions_parses_and_treats_no_server_as_empty():
    ok = SimpleNamespace(returncode=0, stdout="s1\t100\ns2\t200\nbad\tx\n", stderr="")
    assert port_owner.pane_pid_sessions("t", runner=lambda *a, **k: ok) == {100: "s1", 200: "s2"}
    none = SimpleNamespace(returncode=1, stdout="", stderr="no server running on /x")
    assert port_owner.pane_pid_sessions("t", runner=lambda *a, **k: none) == {}
    bad = SimpleNamespace(returncode=1, stdout="", stderr="boom")
    with pytest.raises(port_owner.MeasureError):
        port_owner.pane_pid_sessions("t", runner=lambda *a, **k: bad)


@pytest.mark.asyncio
async def test_detection_is_filed_under_the_owner_not_the_active_session():
    tracker = LocalServersTracker(socket_name="test")
    active_backend = SimpleNamespace(tmux_session="cloude_b")
    manager = SimpleNamespace(_registry=SimpleNamespace(current_backend=lambda: active_backend))
    monitor = SimpleNamespace(
        pattern_detector=SimpleNamespace(extract_port=lambda text: 5173)
    )
    tracker._log_monitor, tracker._session_manager = monitor, manager
    match = PatternMatch("localhost_server", "http://localhost:5173", (), 0)
    with patch.object(ls_module, "find_port_owner", return_value="cloude_a") as fpo, \
            patch.object(ls_module, "port_is_listening", return_value=True):
        await tracker._on_pattern_match(match)
    fpo.assert_called_once_with(5173, "test")
    assert [i.port for i in tracker.list_for_session("cloude_a")] == [5173]
    assert tracker.list_for_session("cloude_b") == []


@pytest.mark.asyncio
async def test_unattributable_or_unmeasured_port_is_dropped_not_filed_under_focus():
    tracker = LocalServersTracker(socket_name="test")
    manager = SimpleNamespace(
        _registry=SimpleNamespace(current_backend=lambda: SimpleNamespace(tmux_session="cloude_b"))
    )
    tracker._log_monitor = SimpleNamespace(
        pattern_detector=SimpleNamespace(extract_port=lambda text: 5173)
    )
    tracker._session_manager = manager
    match = PatternMatch("localhost_server", "http://localhost:5173", (), 0)
    with patch.object(ls_module, "port_is_listening", return_value=True):
        with patch.object(ls_module, "find_port_owner", return_value=None):
            await tracker._on_pattern_match(match)
        with patch.object(
            ls_module, "find_port_owner", side_effect=port_owner.MeasureError("x")
        ):
            await tracker._on_pattern_match(match)
    assert tracker.snapshot() == {}


@pytest.mark.real_tmux
@pytest.mark.skipif(not resolve_tmux_path(), reason="tmux not installed")
@pytest.mark.skipif(not os.path.exists("/usr/sbin/lsof"), reason="lsof missing")
def test_real_tmux_two_panes_only_the_owner_is_named():
    sock = TEST_SOCKET_NAME
    tmux = [resolve_tmux_path(), "-L", sock]
    tmp = tempfile.mkdtemp(prefix="t951_")
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    script = (
        "import socket,time;s=socket.socket();"
        "s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);"
        f"s.bind(('127.0.0.1',{port}));s.listen(1);time.sleep(60)"
    )
    try:
        subprocess.run(tmux + ["new-session", "-d", "-s", "idle_a", "sleep 60"], check=True)
        subprocess.run(
            tmux + ["new-session", "-d", "-s", "owner_b",
                    f"sh -c {shlex.quote(shlex.quote(sys.executable) + ' -c ' + shlex.quote(script) + ' & wait')}"],
            check=True,
        )
        deadline = time.monotonic() + 15
        owner = None
        while time.monotonic() < deadline and owner is None:
            owner = find_port_owner(port, sock)
            if owner is None:
                time.sleep(0.1)
        assert owner == "owner_b"
    finally:
        subprocess.run(tmux + ["kill-server"], check=False, capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)
