
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_PERF = Path(__file__).resolve().parents[1] / "scripts" / "perf"
if str(SCRIPTS_PERF) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_PERF))

from perf_stats import fmt_ms, nearest_rank_percentile, summarize, verdict  # noqa: E402


def test_nearest_rank_percentile_returns_a_real_sample_never_an_interpolation():
    samples = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    p95 = nearest_rank_percentile(samples, 95)
    assert p95 in samples
    assert p95 == 10


def test_nearest_rank_percentile_p50_of_four_values():
    assert nearest_rank_percentile([10, 20, 30, 40], 50) == 20


def test_nearest_rank_percentile_unsorted_input_is_sorted_first():
    assert nearest_rank_percentile([30, 10, 40, 20], 50) == 20


def test_nearest_rank_percentile_rejects_empty_sample():
    with pytest.raises(ValueError):
        nearest_rank_percentile([], 95)


@pytest.mark.parametrize("pct", [0, -1, 100.1, 101])
def test_nearest_rank_percentile_rejects_out_of_range_pct(pct):
    with pytest.raises(ValueError):
        nearest_rank_percentile([1, 2, 3], pct)


def test_summarize_empty_sample_is_none_not_zero():
    result = summarize([])
    assert result.n == 0
    assert result.p50 is None
    assert result.p95 is None
    assert result.p99 is None


def test_summarize_reports_p50_p95_p99_and_count():
    samples = list(range(1, 101))
    result = summarize(samples)
    assert result.n == 100
    assert result.p50 == 50
    assert result.p95 == 95
    assert result.p99 == 99


def test_fmt_ms_renders_none_as_na_and_a_value_with_one_decimal():
    assert fmt_ms(None) == "n/a"
    assert fmt_ms(12.345) == "12.3 ms"
    assert fmt_ms(0.0) == "0.0 ms"


def test_verdict_pass_fail_and_unmeasured():
    assert verdict(40.0, 50.0) == "PASS"
    assert verdict(60.0, 50.0) == "FAIL"
    assert verdict(50.0, 50.0) == "PASS"
    assert verdict(None, 50.0) == "N/A (unmeasured)"
