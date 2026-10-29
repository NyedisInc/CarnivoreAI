
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Dict

import pytest

from src.core.attention import output_holders
from src.core.attention.output_holders import (
    HELD,
    NOT_HELD,
    UNMEASURED,
    descendants,
    probe_output_holders,
)
from src.core.claude_resume_argv import list_process_table

pytestmark = pytest.mark.skipif(
    output_holders._reader() is None, reason="no libproc and no /proc on this platform"
)


def _table() -> Dict[int, int]:
    rows = list_process_table()
    assert rows, "the process table could not be read"
    return {row.pid: row.ppid for row in rows}


def _wait_for(predicate, seconds: float = 3.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def _probe(path: Path) -> str:
    return probe_output_holders([str(path)], root_pid=os.getpid(),
                                process_parents=_table())[str(path)]


def test_a_child_holding_the_file_is_held_and_its_death_flips_it(tmp_path):
    output = tmp_path / "b1.output"
    with open(output, "ab") as sink:
        child = subprocess.Popen(["/bin/sh", "-c", "sleep 30"], stdout=sink, stderr=sink)
    try:
        assert _wait_for(lambda: _probe(output) == HELD)
    finally:
        child.kill()
        child.wait()
    assert _probe(output) == NOT_HELD


def test_a_grandchild_alone_holding_the_file_is_held(tmp_path):
    output = tmp_path / "b2.output"
    output.write_text("")
    script = 'sleep 30 >> "$1" 2>&1 & echo started; wait'
    child = subprocess.Popen(["/bin/sh", "-c", script, "sh", str(output)],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        assert child.stdout.readline().strip() == b"started"
        assert _wait_for(lambda: _probe(output) == HELD)
        grandchildren = [pid for pid, ppid in _table().items() if ppid == child.pid]
        assert len(grandchildren) == 1
        os.kill(grandchildren[0], 9)
        assert _wait_for(lambda: _probe(output) == NOT_HELD)
    finally:
        child.kill()
        child.wait()


def test_the_root_itself_holding_the_file_does_not_count(tmp_path):
    output = tmp_path / "b3.output"
    with open(output, "ab"):
        assert _probe(output) == NOT_HELD


def test_a_holder_outside_the_root_s_tree_does_not_count(tmp_path):
    output = tmp_path / "b4.output"
    with open(output, "ab") as sink:
        child = subprocess.Popen(["/bin/sh", "-c", "sleep 30"], stdout=sink, stderr=sink)
    try:
        table = _table()
        assert _wait_for(lambda: probe_output_holders(
            [str(output)], root_pid=os.getpid(), process_parents=_table())[str(output)] == HELD)
        answer = probe_output_holders([str(output)], root_pid=child.pid, process_parents=table)
        assert answer[str(output)] == NOT_HELD
    finally:
        child.kill()
        child.wait()


def test_a_missing_file_is_not_held_and_the_symlinked_tmp_spelling_matches(tmp_path):
    assert _probe(tmp_path / "never-created.output") == NOT_HELD
    output = tmp_path / "b5.output"
    alias = tmp_path / "alias.output"
    with open(output, "ab") as sink:
        child = subprocess.Popen(["/bin/sh", "-c", "sleep 30"], stdout=sink, stderr=sink)
    alias.symlink_to(output)
    try:
        assert _wait_for(lambda: _probe(alias) == HELD)
    finally:
        child.kill()
        child.wait()


def test_whatever_could_not_be_looked_at_is_unmeasured(tmp_path, monkeypatch):
    output = tmp_path / "b6.output"
    output.write_text("")
    path = str(output)
    assert probe_output_holders([path], root_pid=None, process_parents={1: 0})[path] == UNMEASURED
    assert probe_output_holders([path], root_pid=os.getpid(), process_parents=None)[path] == UNMEASURED
    with open(output, "ab") as sink:
        child = subprocess.Popen(["/bin/sh", "-c", "sleep 30"], stdout=sink, stderr=sink)
    try:
        table = _table()
        assert probe_output_holders([path], root_pid=os.getpid(), process_parents=table,
                                    budget_seconds=-1.0)[path] == UNMEASURED

        def refuse(pid: int):
            raise output_holders._Unmeasurable("EPERM")

        monkeypatch.setattr(output_holders, "_reader", lambda: refuse)
        assert probe_output_holders([path], root_pid=os.getpid(),
                                    process_parents=table)[path] == UNMEASURED
    finally:
        child.kill()
        child.wait()


def test_no_free_slot_is_unmeasured(tmp_path, monkeypatch):
    output = tmp_path / "b7.output"
    output.write_text("")
    monkeypatch.setattr(output_holders, "SLOT_WAIT_SECONDS", 0.01)
    held = [output_holders._SLOTS.acquire() for _ in range(output_holders.MAX_CONCURRENT_PROBES)]
    try:
        answer = probe_output_holders([str(output)], root_pid=os.getpid(),
                                      process_parents={os.getpid() + 1: os.getpid()})
        assert answer[str(output)] == UNMEASURED
    finally:
        for _ in held:
            output_holders._SLOTS.release()


def test_descendants_walks_the_tree_below_the_root_only():
    assert descendants(10, {11: 10, 12: 11, 13: 12, 20: 1, 10: 1}) == [11, 12, 13]
    assert descendants(10, {}) == []
