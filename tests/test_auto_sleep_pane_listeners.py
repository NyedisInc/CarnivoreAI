
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.core.auto_sleep import pane_listeners
from src.core.auto_sleep.pane_listeners import (
    ListenerSnapshot,
    MeasureError,
    parse_lsof_pids,
)
from src.core.conversation_writers import Proc, ProcessTable


def _lsof(monkeypatch, returncode=0, stdout="", stderr="", raises=None):

    def run(argv, **_kwargs):
        assert argv[0] == pane_listeners.LSOF_PATH and "-sTCP:LISTEN" in argv
        if raises is not None:
            raise raises
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(pane_listeners.subprocess, "run", run)


def test_parse_reads_only_process_lines():
    assert parse_lsof_pids("p12\nf3\np40\nf5\n") == frozenset({12, 40})


def test_parse_refuses_a_process_line_that_is_not_a_pid():
    with pytest.raises(MeasureError):
        parse_lsof_pids("pabc\n")


def test_a_process_holding_a_listen_socket_is_seen_by_the_kernel_read_and_a_closed_one_is_not():
    import os
    import socket

    from src.core.auto_sleep.pane_ports import pid_holds_listener

    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    try:
        assert pid_holds_listener(os.getpid()) is True
    finally:
        server.close()
    assert pid_holds_listener(os.getpid()) is False


def test_the_real_snapshot_never_spawns_lsof(monkeypatch):
    monkeypatch.setattr(pane_listeners, "read_process_table", lambda: ProcessTable.from_rows([Proc(1, 0, "t", "launchd")]))
    snap = pane_listeners.take_snapshot()
    assert snap.listeners is None


def _snapshot(listeners):
    rows = [Proc(1, 0, "t", "launchd"), Proc(10, 1, "t", "claude"),
            Proc(11, 10, "t", "zsh"), Proc(12, 11, "t", "node"), Proc(20, 1, "t", "node")]
    return ListenerSnapshot(frozenset(listeners), ProcessTable.from_rows(rows))


def test_a_grandchild_listener_is_the_panes():
    assert _snapshot({12, 20}).pane_listeners(10) == [12]


def test_a_listener_outside_the_tree_is_not_the_panes():
    assert _snapshot({20}).pane_listeners(10) == []


def test_a_pane_pid_missing_from_the_table_cannot_measure():
    with pytest.raises(MeasureError):
        _snapshot({12}).pane_listeners(99)


def test_the_agents_own_listener_is_not_a_dev_server_but_its_child_listener_is():
    assert _snapshot({10}).pane_listeners(10, exclude_pid=10) == []
    assert _snapshot({10, 12}).pane_listeners(10, exclude_pid=10) == [12]
    assert _snapshot({10}).pane_listeners(10) == [10]
    assert _snapshot({10}).holder_label(10) == "claude 10"
