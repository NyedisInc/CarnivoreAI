
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_PERF = Path(__file__).resolve().parents[2] / "scripts" / "perf"
if str(SCRIPTS_PERF) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_PERF))

import latency_harness  # noqa: E402
from latency_harness import exit_code, idle_cpu_percent, longest_gap_ms, parse_cputime  # noqa: E402
from perf_stats import nearest_rank_percentile  # noqa: E402


def test_percentiles_and_stall_math():
    samples = list(range(1, 101))
    assert nearest_rank_percentile(samples, 50) == 50
    assert nearest_rank_percentile(samples, 95) == 95
    assert nearest_rank_percentile(samples, 99) == 99
    assert longest_gap_ms([0.0, 0.01, 0.31, 0.32]) == pytest.approx(300.0)
    assert longest_gap_ms([1.0]) is None and longest_gap_ms([]) is None
    assert parse_cputime("1:02.50") == 62.5 and parse_cputime("1:00:01.00") == 3601.0
    assert idle_cpu_percent(10.0, 10.6, 60.0) == pytest.approx(1.0)
    with pytest.raises(ValueError):
        idle_cpu_percent(5.0, 4.0, 60.0)


def test_exit_nonzero_when_nothing_was_measured():
    good = {"measured": 10}
    assert exit_code({"keystroke": good}, ["keystroke"]) == 0
    assert exit_code({}, ["keystroke"]) == 1
    assert exit_code({"keystroke": {"measured": 0}}, ["keystroke"]) == 1
    assert exit_code({"keystroke": {"error": "x", "measured": 5}}, ["keystroke"]) == 1
    assert exit_code({"keystroke": good}, ["keystroke", "burst"]) == 1
    assert exit_code({}, []) == 1


def _trap_run(monkeypatch, doc=None):
    calls = []

    async def fake_run(args):
        calls.append(args)
        if doc is None:
            raise AssertionError("run() must not start above the load limit")
        return doc

    monkeypatch.setattr(latency_harness, "run", fake_run)
    return calls


@pytest.mark.parametrize("load", [9.0, 4.01, None])
def test_budget_mode_refuses_when_load_over_four(monkeypatch, capsys, load):
    calls = _trap_run(monkeypatch)
    monkeypatch.setattr(latency_harness, "read_loadavg_1m", lambda: load)
    assert latency_harness.main(["--budget"]) == 2
    out = capsys.readouterr().out
    assert "could not measure" in out and "pass" not in out.lower().replace("never a pass", "")
    assert calls == []


def test_budget_mode_load_boundary_and_after_check(monkeypatch, capsys):
    ok = {"revision": "x", "machine": "m", "selected": list(latency_harness.METRICS), "results": {}}
    _trap_run(monkeypatch, ok)
    monkeypatch.setattr(latency_harness, "read_loadavg_1m", lambda: 4.0)
    assert latency_harness.main(["--budget"]) == 1
    reads = iter([3.0, 9.0])
    monkeypatch.setattr(latency_harness, "read_loadavg_1m", lambda: next(reads))
    assert latency_harness.main(["--budget"]) == 2
    assert "tainted" in capsys.readouterr().out


def _res(p50=8.0, p95=16.0, gap=250.0, closes=0, boot=2.5):
    return {"keystroke": {"measured": 5, "p50_ms": p50, "p95_ms": p95},
            "burst": {"measured": 1, "longest_gap_ms": gap, "overflow_closes": closes},
            "boot": {"measured": 3, "health_median_s": boot}}


def test_budget_lines_pass_fail_and_never_pass_unmeasured():
    from perf_budget import budget_exit_code, budget_lines
    lines = budget_lines(_res())
    assert lines[0] == "echo p50: 8 ms <= 8 ms pass"
    assert [ln for ln in lines if "pass" in ln.split(":")[1]].__len__() == 4
    assert len(lines) == 4 + 4 + 3
    for ln in lines[4:]:
        assert "not measured" in ln and "pass" not in ln.split("(")[0]
    assert budget_exit_code(lines) == 1
    assert budget_lines(_res(p50=8.1))[0].endswith("fail")
    assert budget_lines(_res(gap=250.1))[2].split("(")[0].endswith("fail ")
    assert "fail" in budget_lines(_res(gap=1.0, closes=1))[2]
    assert budget_lines(_res(boot=2.6))[3].endswith("fail")
    empty = budget_lines({"keystroke": {"measured": 0}, "burst": {"error": "x", "measured": 3}})
    assert all("pass" not in ln.split(":", 1)[1].split("(")[0] for ln in empty)
    assert budget_exit_code(["a: 1 ms <= 8 ms pass", "b: tracked, no target, not measured"]) == 0
