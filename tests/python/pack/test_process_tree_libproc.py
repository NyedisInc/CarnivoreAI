
import subprocess

import pytest

from src.core import conversation_writers, libproc_snapshot
from src.core.pack.load import process_tree

T = libproc_snapshot.TaskRow


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(process_tree.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(process_tree, "_baseline", None)
    monkeypatch.setattr(process_tree, "_window_cpu", {})
    return now


def _tables(monkeypatch, *tables):
    it = iter(tables)
    monkeypatch.setattr(libproc_snapshot, "task_table", lambda: next(it))


def test_cpu_is_delta_over_wall_time_and_none_without_baseline(monkeypatch, clock):
    _tables(monkeypatch, [T(1, 0, 0, 10), T(2, 1, 1_000_000_000, 20)],
            [T(1, 0, 0, 10), T(2, 1, 2_000_000_000, 20), T(3, 1, 500_000_000, 5)])
    assert process_tree._read_libproc() is None
    clock[0] += 4.0
    rows = {r.pid: r for r in process_tree._read_libproc()}
    assert rows[1].cpu == 0.0
    assert rows[2].cpu == pytest.approx(25.0)
    assert rows[3].cpu == pytest.approx(12.5)
    assert rows[2].rss_kb == 20


def test_short_window_reuses_last_full_window_and_stale_baseline_falls_back(monkeypatch, clock):
    _tables(monkeypatch, [T(1, 0, 0, 1)], [T(1, 0, 400_000_000, 1)], [T(1, 0, 1_000_000_000, 1)], [T(1, 0, 1_000_000_000, 1)],
            [T(1, 0, 2_000_000_000, 1)], [T(1, 0, 0, 1)])
    process_tree._read_libproc()
    clock[0] += 0.5
    assert process_tree._read_libproc() is None
    clock[0] += 3.5
    assert process_tree._read_libproc()[0].cpu == pytest.approx(25.0)
    clock[0] += 0.1
    assert process_tree._read_libproc()[0].cpu == pytest.approx(25.0)
    clock[0] += 2.0
    assert process_tree._read_libproc()[0].cpu == pytest.approx(1.0 / 2.1 * 100.0)
    clock[0] += 500
    assert process_tree._read_libproc() is None


def test_read_falls_back_to_ps_and_prefers_libproc(monkeypatch, clock):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="  7 1 1.5 99\n", stderr="")

    monkeypatch.setattr(process_tree.subprocess, "run", fake_run)
    monkeypatch.setattr(libproc_snapshot, "task_table", lambda: None)
    assert process_tree.read() == [process_tree.Proc(7, 1, 1.5, 99)]
    monkeypatch.setattr(libproc_snapshot, "task_table", lambda: [T(7, 1, 0, 99)])
    assert process_tree.read() == [process_tree.Proc(7, 1, 1.5, 99)]
    clock[0] += 3
    assert process_tree.read() == [process_tree.Proc(7, 1, 0.0, 99)] and len(calls) == 2
    monkeypatch.setattr(process_tree.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("no ps")))
    monkeypatch.setattr(libproc_snapshot, "task_table", lambda: None)
    assert process_tree.read() is None


def test_read_process_table_uses_ps_when_libproc_has_no_rows(monkeypatch):
    monkeypatch.setattr(libproc_snapshot, "snapshot", lambda max_age=0.0: None)
    monkeypatch.setattr(conversation_writers, "read_ps_text", lambda *a: "    5     1 Thu Oct 15 11:52:02 2026 /bin/sleep 3\n")
    assert [p.pid for p in conversation_writers.read_process_table().rows.values()] == [5]
