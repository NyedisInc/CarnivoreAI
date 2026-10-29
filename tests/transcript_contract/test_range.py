
from __future__ import annotations

import json

from src.core.transcript_contract import parse_range
from src.core.transcript_manifest.tail import line_serial
from tests.transcript_contract.fixture_lines import load


def test_offsets_watermark_and_torn_tail() -> None:
    first = load("claude")[0]["line"].encode() + b"\n"
    second = json.dumps({"type": "mode", "mode": "<str>", "sessionId": "<str>"}).encode() + b"\n"
    torn = b'{"type":"mode","mo'
    base = 1000
    rng = parse_range(first + second + torn, base, "claude")
    assert [(ln.offset, ln.length) for ln in rng.lines] == [
        (base, len(first)), (base + len(first), len(second))]
    assert rng.complete_end == base + len(first) + len(second)
    assert rng.torn_bytes == len(torn)
    assert rng.last_serial == line_serial(second[:-1])
    assert all(ln.parsed.clean for ln in rng.lines)


def test_undecodable_and_empty_ranges_drop_nothing() -> None:
    rng = parse_range(b"\xff\xfe\n" + b"\n", 0, "codex")
    assert [ln.parsed.status for ln in rng.lines] == ["unparseable", "blank"]
    assert rng.complete_end == 4
    empty = parse_range(b"", 50, "claude")
    assert empty.lines == () and empty.complete_end == 50 and empty.last_serial is None
