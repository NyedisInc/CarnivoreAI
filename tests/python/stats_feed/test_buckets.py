
from __future__ import annotations

from src.core.stats_feed.model import WINDOWS, Classes, fold, trailing_rate, window_start

NOW = 1_700_000_000.0


def test_every_window_aligns_to_its_bar_width():
    for spec in WINDOWS.values():
        start = window_start(spec, NOW)
        assert start % spec.bucket_s == 0 and NOW - start < spec.bucket_s * spec.buckets


def test_gaps_and_held_bars_are_none_and_empty_bars_are_zero():
    spec = WINDOWS["1h"]
    start = window_start(spec, NOW)
    bars = fold(spec, NOW, {start + 60: Classes(1, 2, 3, 4)}, {}, [(start + 120, start + 180)], start + 3000)
    assert bars[0] == Classes() and bars[1] == Classes(1, 2, 3, 4)
    assert bars[2] is None and bars[3] == Classes()
    assert bars[-1] is None


def test_rate_uses_the_trailing_240_to_300_seconds():
    minute = int(NOW // 60) * 60
    rate = trailing_rate({minute - 240: Classes(0, 0, 0, 300), minute - 300: Classes(0, 0, 0, 9999)}, NOW)
    assert rate["span_seconds"] == round(NOW - (minute - 240), 1) and rate["out"] == round(300 / rate["span_seconds"], 1)
