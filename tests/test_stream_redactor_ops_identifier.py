
from __future__ import annotations

import base64
import random
from typing import List, Tuple

import pytest

from src.core.message_model_secrets import (
    DETECTOR_OP_SERVICE_ACCOUNT,
    scan_text,
)
from src.core.stream_redactor import StreamRedactor

MARKER = "op" + "s_"

IDENTIFIER = "test_router_dr" + "ops_emit_when_all_three_channels_unconfigured"

REPRO = ("#: ``test_router_drops_emit_whe\r\nn_all_three_channels_unconfigur"
         "\r\ned``, where\r\n")


def _token(seed: int, size: int = 120) -> str:
    rng = random.Random(seed)
    body = base64.b64encode(b'{"s' + rng.randbytes(size)).decode()
    return MARKER + body


def _run(chunks: List[str], idle_flush: bool = False) -> str:
    redactor = StreamRedactor()
    out = []
    for chunk in chunks:
        out.append(redactor.feed(chunk))
        if idle_flush:
            out.append(redactor.flush())
    out.append(redactor.flush(end=True))
    return "".join(out)


def _wrap(prefix: str, text: str, width: int) -> Tuple[str, List[int]]:
    line = prefix + text
    stream: List[str] = []
    positions: List[int] = []
    for index, char in enumerate(line):
        if index and index % width == 0:
            stream.append("\r\n")
        if index >= len(prefix):
            positions.append(len("".join(stream)))
        stream.append(char)
    stream.append("\r\n")
    return "".join(stream), positions


def _assert_body_starred(raw: str, out: str, body_positions: List[int]) -> None:
    assert len(out) == len(raw), "length must be preserved exactly"
    wanted = set(body_positions)
    for index, (before, after) in enumerate(zip(raw, out)):
        if index in wanted:
            assert after == "*", f"body character at {index} was released"
        elif before in "\r\n\x1b":
            assert after == before, f"control byte at {index} was changed"




def test_the_issue_reproduction_passes_through_unchanged() -> None:
    assert _run([REPRO]) == REPRO


def test_the_identifier_unwrapped_passes_through_unchanged() -> None:
    raw = "def " + IDENTIFIER + "():\r\n"
    assert _run([raw]) == raw


@pytest.mark.parametrize("width", range(12, 81))
def test_the_identifier_wrapped_at_any_width_passes_through(width: int) -> None:
    raw, _ = _wrap("#: ``", IDENTIFIER + "``, where", width)
    assert _run([raw]) == raw


@pytest.mark.parametrize("word", ["dr", "st", "lo", "pr", "sh", "cr", "h"])
def test_other_ops_words_before_a_long_identifier_pass_through(word: str) -> None:
    raw = f"  x.{word}{MARKER}the_value_that_a_long_snake_case_name_carries_on\r\n"
    assert _run([raw]) == raw


def test_redaction_mode_scan_finds_no_token_in_the_identifier() -> None:
    assert scan_text(IDENTIFIER, [DETECTOR_OP_SERVICE_ACCOUNT],
                     trust_vendor_marker=True) == []




def test_redaction_mode_scan_still_finds_the_token_glued_to_a_word() -> None:
    token = _token(7)
    findings = scan_text("dr" + token, [DETECTOR_OP_SERVICE_ACCOUNT],
                         trust_vendor_marker=True)
    assert [(f.detector, f.offset, f.length) for f in findings] == [
        (DETECTOR_OP_SERVICE_ACCOUNT, len("dr"), len(token))]


def test_a_token_whose_capital_comes_late_is_still_starred() -> None:
    body = "abcdefghij" * 5 + "Q7W2E9R4"
    raw = "export T=" + MARKER + body + "\r\n"
    out = _run([raw])
    start = raw.index(MARKER) + len(MARKER)
    _assert_body_starred(raw, out, list(range(start, start + len(body))))


@pytest.mark.parametrize("glue", ["", "dr", "drops", "\x1b[32m", "\\u001b[32m",
                                  "\\n", "word "])
def test_a_token_glued_onto_anything_is_starred(glue: str) -> None:
    token = _token(11)
    raw = "value: " + glue + token + " done\r\n"
    out = _run([raw])
    start = raw.index(token) + len(MARKER)
    _assert_body_starred(raw, out, list(range(start, start + len(token) - len(MARKER))))


@pytest.mark.parametrize("width", range(12, 81))
def test_a_token_wrapped_at_any_width_is_starred(width: int) -> None:
    token = _token(width)
    raw, positions = _wrap("#: ``test_router_", token + "``, where", width)
    body = positions[len(MARKER):len(token)]
    _assert_body_starred(raw, _run([raw]), body)


def test_a_wrapped_token_split_across_reads_at_every_offset_is_starred() -> None:
    token = _token(31)
    raw, positions = _wrap("#: ``test_router_", token + "``, where", 31)
    body = positions[len(MARKER):len(token)]
    for cut in range(1, len(raw)):
        for idle in (False, True):
            _assert_body_starred(raw, _run([raw[:cut], raw[cut:]], idle), body)


def test_the_check_goes_red_on_an_unredacted_token() -> None:
    token = _token(3)
    raw, positions = _wrap("x ", token, 31)
    with pytest.raises(AssertionError):
        _assert_body_starred(raw, raw, positions[len(MARKER):])
