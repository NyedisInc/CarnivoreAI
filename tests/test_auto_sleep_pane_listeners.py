
from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from src.core.auto_sleep import pane_listeners
from src.core.auto_sleep.pane_listeners import (
    ListenerSnapshot,
    MeasureError,
    listening_pids,
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


def test_listening_pids_reads_exit_zero(monkeypatch):
    _lsof(monkeypatch, stdout="p7\nf4\n")
    assert listening_pids() == frozenset({7})


def test_lsof_silent_exit_one_is_nothing_listening(monkeypatch):
    _lsof(monkeypatch, returncode=1)
    assert listening_pids() == frozenset()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"returncode": 1, "stderr": "lsof: unknown option"},
        {"returncode": 2},
        {"returncode": 0, "stdout": ""},
        {"raises": subprocess.TimeoutExpired("lsof", 5)},
        {"raises": FileNotFoundError("lsof")},
    ],
    ids=["exit 1 with an error", "exit 2", "exit 0 naming nothing", "timeout", "missing"],
)
def test_every_other_lsof_outcome_cannot_measure(monkeypatch, kwargs):
    _lsof(monkeypatch, **kwargs)
    with pytest.raises(MeasureError):
        listening_pids()


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
