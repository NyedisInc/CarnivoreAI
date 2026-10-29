
from __future__ import annotations

import pytest

from tests.synthetic_credentials import (
    anthropic_key,
    aws_key_id,
    github_token,
    synthetic_body,
)
from src.core.stream_redactor import StreamRedactor
from tests.test_stream_redactor_bypass import _assert_gone, _redact

TOKEN = github_token()
HEAD, TAIL = TOKEN[:22], TOKEN[22:]
ANTHROPIC = anthropic_key()
A_HEAD, A_TAIL = ANTHROPIC[:40], ANTHROPIC[40:]

LAYOUTS = {
    "claude reply, 2-space hanging indent": ("⏺ here: {h}\r\n  {t}\r\n"),
    "tool output, 5-space indent": ("  ⎿  {h}\r\n     {t}\r\n"),
    "light box border": ("│ > {h} │\r\n│   {t} │\r\n"),
    "heavy box border": ("┃ {h}┃\r\n┃ {t}   ┃\r\n"),
    "double box border": ("║ {h} ║\n║ {t} ║\n"),
    "ascii pipe border": ("| {h} |\r\n| {t} |\r\n"),
    "trailing spaces before the break": ("{h}    \r\n{t}\r\n"),
    "tab indent": ("{h}\n\t{t}\n"),
}


def _expected(raw: str, head: str, tail: str) -> str:
    return raw.replace(head, "*" * len(head)).replace(tail, "*" * len(tail))


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
def test_a_wrapped_token_in_a_real_layout_is_starred_and_nothing_else(layout: str) -> None:
    raw = LAYOUTS[layout].format(h=HEAD, t=TAIL)
    assert raw.count(HEAD) == 1 and raw.count(TAIL) == 1
    out = _assert_gone(raw)
    assert out == _expected(raw, HEAD, TAIL)


def test_an_anthropic_key_wrapped_before_its_head_matches_alone() -> None:
    raw = "⏺ " + A_HEAD + "\r\n  " + A_TAIL + "\r\n"
    out = _assert_gone(raw, ANTHROPIC)
    assert out == _expected(raw, A_HEAD, A_TAIL)


def test_keys_one_per_indented_line_are_each_still_found() -> None:
    first, second = aws_key_id(), aws_key_id()
    raw = "  " + first + "\r\n  " + second + "\r\n"
    out = _redact(raw)
    assert first not in out and second not in out
    assert out == _expected(raw, first, second)


@pytest.mark.parametrize(
    "raw",
    [
        "│ building the release │\r\n│   artifacts now      │\r\n",
        "⏺ the build\r\n  finished cleanly\r\n",
        "| name | value |\r\n| alpha | beta |\r\n",
    ],
    ids=["box", "indent", "table"],
)
def test_ordinary_boxed_or_indented_text_is_untouched(raw: str) -> None:
    assert _redact(raw) == raw


@pytest.mark.parametrize("gap", ["\r\n", "\n", "\r\n  ", "\r\n│ ", "\r\n12 "],
                         ids=["crlf", "lf", "indent", "border", "gutter"])
def test_a_quoted_assignment_does_not_star_the_next_line(gap: str) -> None:
    raw = ('CONFIG_KEY = "message_archive"' + gap
           + 'CONFIG_ENABLED_FIELD = "enabled"\r\n')
    assert _redact(raw) == raw



GOOGLE = "AI" + "za" + synthetic_body(35)


@pytest.mark.parametrize(
    "layout",
    [
        "⏺ Your new token is\r\n  {h}\r\n  {t}\r\n",
        "Your new token is\r\n{h}\r\n{t}\r\n",
        "  ⎿  exported the key\r\n     {h}\r\n     {t}\r\n",
        "⏺ use {h}\r\n  {t}\r\n  then restart\r\n",
    ],
    ids=["prose-row-above-indent", "prose-row-above-bare", "tool-output", "prose-row-below"],
)
@pytest.mark.parametrize("key", [TOKEN, ANTHROPIC, GOOGLE], ids=["github", "anthropic", "google"])
def test_a_wrap_join_that_glues_prose_onto_a_key_still_stars_it(layout: str, key: str) -> None:
    """MUTATION: put the word boundary back on the redaction patterns."""
    cut = len(key) // 2
    raw = layout.format(h=key[:cut], t=key[cut:])
    _assert_gone(raw, key)


@pytest.mark.parametrize(
    "prefix,sep",
    [
        ("▌ ", "\r\n"), ("▏ ", "\r\n"), ("  ", "\r\r\n"), ("> ", "\r\n"),
        ("  ", "\r\n"), ("+ ", "\r\n"), ("+", "\n"), ("- ", "\n"),
        ("  12 │ ", "\r\n"), ("7: ", "\n"), ("* ", "\n"),
    ],
    ids=["codex-cell", "eighth-block", "cr-cr-lf", "quote", "nbsp", "diff-plus",
         "bare-plus", "diff-minus", "line-number-box", "line-number-colon", "bullet"],
)
def test_every_continuation_prefix_is_bridged(prefix: str, sep: str) -> None:
    raw = "key " + A_HEAD + sep + prefix + A_TAIL + sep
    out = _assert_gone(raw, ANTHROPIC)
    assert out.count(sep) == raw.count(sep)
    assert prefix in out


def test_a_scrollbar_column_on_both_rows_is_bridged() -> None:
    raw = "key " + A_HEAD + " ░\r\n  " + A_TAIL + " ░\r\n"
    out = _assert_gone(raw, ANTHROPIC)
    assert out.count("░") == 2


def _chunked(pieces: list, flush_after: tuple) -> str:
    redactor = StreamRedactor()
    out = []
    for index, piece in enumerate(pieces):
        out.append(redactor.feed(piece))
        if index in flush_after:
            out.append(redactor.flush())
    out.append(redactor.flush(end=True))
    return "".join(out)


def test_a_starred_head_still_stars_the_row_that_arrives_after_a_pause() -> None:
    head, tail = ANTHROPIC[:70], ANTHROPIC[70:]
    pieces = ["⏺ " + head + "\r\n", "  ", tail + "\r\n"]
    out = _chunked(pieces, (0, 1))
    raw = "".join(pieces)
    assert len(out) == len(raw)
    for start in range(len(ANTHROPIC) - 11):
        assert ANTHROPIC[start:start + 12] not in out


def test_a_marker_split_by_a_pause_is_still_recognised() -> None:
    pieces = ["token s\r\n", "  " + ANTHROPIC[1:] + "\r\n"]
    out = _chunked(pieces, (0,))
    assert ANTHROPIC[1:13] not in out
    assert "*" * 20 in out


def test_a_head_before_a_waiting_row_break_is_held_by_a_pause() -> None:
    redactor = StreamRedactor()
    first = redactor.feed("key " + TOKEN[:24] + "\r\n")
    first += redactor.flush()
    assert TOKEN[4:24] not in first
    rest = redactor.feed("  " + TOKEN[24:] + "\r\n") + redactor.flush(end=True)
    assert TOKEN[4:24] not in first + rest and TOKEN[24:] not in rest


def test_an_ordinary_line_before_a_pause_is_not_withheld() -> None:
    redactor = StreamRedactor()
    line = "Server listening on port 8080\r\n"
    assert redactor.feed(line) + redactor.flush() == line


def test_a_hard_wrapped_minisign_body_line_is_starred_whole() -> None:
    import base64
    import secrets as random_source
    body = base64.b64encode(random_source.token_bytes(158)).decode()
    header = "untrusted comment: mini" + "sign encrypted secret key"
    rows = [body[i:i + 80] for i in range(0, len(body), 80)]
    raw = header + "\r\n" + "\r\n  ".join(rows) + "\r\nafter the key\r\n"
    out = _redact(raw)
    for row in rows:
        assert row[:12] not in out
    assert out.endswith("after the key\r\n")
