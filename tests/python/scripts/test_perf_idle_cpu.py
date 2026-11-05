from __future__ import annotations

import sys
from pathlib import Path

PERF = Path(__file__).resolve().parents[3] / "scripts" / "perf"
sys.path.insert(0, str(PERF))

import run_baseline  # noqa: E402
from perf_client import ProcessSample  # noqa: E402


def test_idle_sample_reports_the_delta_over_its_window_not_the_lifetime_average(monkeypatch) -> None:
    cpu = iter([10.0, 10.3])
    clock = iter([100.0, 103.0])
    monkeypatch.setattr(run_baseline, "cpu_seconds", lambda pid: next(cpu))
    monkeypatch.setattr(run_baseline.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(run_baseline.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        run_baseline, "sample_process", lambda pid: ProcessSample(cpu_percent=99.0, rss_kb=5, child_count=2)
    )
    out = run_baseline._idle_sample(1234, seconds=3.0)
    assert (out["rss_kb"], out["child_count"]) == (5, 2)
    assert abs(out["cpu_percent"] - 10.0) < 1e-6


def test_idle_sample_of_a_gone_pid_is_all_none(monkeypatch) -> None:
    def gone(pid: int) -> float:
        raise RuntimeError("ps could not read pid")

    monkeypatch.setattr(run_baseline, "cpu_seconds", gone)
    monkeypatch.setattr(run_baseline.time, "sleep", lambda s: None)
    assert run_baseline._idle_sample(1, seconds=0.0) == {
        "cpu_percent": None, "rss_kb": None, "child_count": None,
    }


def test_idle_sample_with_cputime_going_backwards_is_all_none(monkeypatch) -> None:
    cpu = iter([10.0, 9.0])
    clock = iter([0.0, 10.0])
    monkeypatch.setattr(run_baseline, "cpu_seconds", lambda pid: next(cpu))
    monkeypatch.setattr(run_baseline.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(run_baseline.time, "sleep", lambda s: None)
    assert run_baseline._idle_sample(1, seconds=10.0) == {
        "cpu_percent": None, "rss_kb": None, "child_count": None,
    }
