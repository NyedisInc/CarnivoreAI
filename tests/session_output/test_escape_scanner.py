
from __future__ import annotations

import random
import time

from src.core.session_output.escape_scanner import MAX_CODE_BYTES, EscapeScanner, Event

STREAM = (b"plain text \x1b[1mbold\x1b[0m\x1b]0;window title\x07"
          b"\x1b]9;build done\x07 more \x07 \x1b]9;4;1;40\x1b\\"
          b"\x1b]777;notify;Deploy;all green\x07\x1b]52;c;c2VjcmV0\x07"
          b"\x1b]99;d=0;Kitty title\x1b\\\x1b]99;p=body;kitty body\x1b\\\x1b]9;4;0\x07")
EXPECTED = [Event("notify", "", "build done"), Event("bell"), Event("progress", "1", "", 40),
            Event("notify", "Deploy", "all green"), Event("notify", "Kitty title", "kitty body"),
            Event("progress", "0", "", None)]


def _feed_all(chunks):
    scanner, out = EscapeScanner(), []
    for chunk in chunks:
        out += scanner.feed(chunk)
    return out


def test_whole_byte_by_byte_and_random_splits_give_the_same_events():
    assert _feed_all([STREAM]) == EXPECTED
    assert _feed_all([STREAM[i:i + 1] for i in range(len(STREAM))]) == EXPECTED
    rng = random.Random(2732)
    for _ in range(200):
        cuts = sorted(rng.sample(range(1, len(STREAM)), rng.randint(1, 12)))
        parts = [STREAM[a:b] for a, b in zip([0] + cuts, cuts + [len(STREAM)])]
        assert _feed_all(parts) == EXPECTED


def test_a_bel_that_ends_an_osc_is_not_a_bell():
    assert EscapeScanner().feed(b"\x1b]2;title\x07\x1b]9;hi\x07") == [Event("notify", "", "hi")]


def test_an_overlong_code_is_skipped_and_the_scanner_resyncs():
    big = b"\x1b]9;" + b"x" * (MAX_CODE_BYTES + 10) + b"\x07"
    assert _feed_all([big[:3000], big[3000:], b"\x1b]9;after\x07"]) == [Event("notify", "", "after")]


def test_ten_thousand_title_updates_give_no_events_and_store_nothing():
    scanner = EscapeScanner()
    for n in range(10000):
        assert scanner.feed(b"\x1b]0;title %d\x07\x1b]52;c;QUJD\x07" % n) == []
        assert len(scanner._buf) == 0


def test_a_flood_drops_to_counting():
    scanner = EscapeScanner()
    events = scanner.feed(b"\x1b]9;n\x07" * 100)
    assert len(events) == 16 and scanner.dropped == 84


def test_one_megabyte_each_of_text_titles_and_bells_stays_inside_its_budget():
    budgets = {b"x" * 8192: 0.05, (b"\x1b]2;" + b"t" * 60 + b"\x07") * 128: 0.25, b"\x07" * 8192: 0.05}
    for chunk, budget in budgets.items():
        scanner = EscapeScanner()
        start = time.perf_counter()
        for _ in range((1 << 20) // len(chunk)):
            scanner.feed(chunk)
        assert time.perf_counter() - start < budget, (chunk[:8], time.perf_counter() - start)
