
from __future__ import annotations

import base64
import secrets
import string
from typing import Callable, Iterable, List, Sequence, Tuple

import pytest

from src.core.message_model_secrets import (
    DETECTOR_AWS_ACCESS_KEY_ID,
    DETECTOR_GITHUB_TOKEN,
    DETECTOR_HIGH_ENTROPY_ASSIGNMENT,
    DETECTOR_MINISIGN_SECRET_KEY,
    DETECTOR_PEM_PRIVATE_KEY,
    DETECTOR_SLACK_TOKEN,
    scan_text,
)
from src.core.stream_redactor import (
    REDACTION_CHAR,
    RedactionStats,
    StreamRedactor,
)

_BASE62 = string.ascii_letters + string.digits


def _generated(detector: str, build: Callable[[], str]) -> str:
    for _ in range(200):
        candidate = build()
        found = scan_text(candidate)
        if len(found) == 1 and found[0].detector == detector:
            return candidate
    raise RuntimeError(f"could not generate a fixture for {detector}")


def _draw(alphabet: str, length: int) -> str:
    return "".join(secrets.choice(alphabet) for _ in range(length))


GITHUB = _generated(
    DETECTOR_GITHUB_TOKEN, lambda: "ghp_" + _draw(_BASE62, 36)
)
AWS_KEY_ID = _generated(
    DETECTOR_AWS_ACCESS_KEY_ID,
    lambda: "AKIA" + _draw(string.ascii_uppercase + string.digits, 16),
)
SLACK = _generated(
    DETECTOR_SLACK_TOKEN,
    lambda: "xoxb-" + "-".join(_draw(_BASE62, 12) for _ in range(3)),
)

ASSIGNMENT_VALUE = _generated(
    DETECTOR_HIGH_ENTROPY_ASSIGNMENT,
    lambda: "api_key = " + _draw(_BASE62, 30),
)[len("api_key = "):]
ASSIGNMENT = "api_key = " + ASSIGNMENT_VALUE

ORDINARY = (
    "\x1b[2J\x1b[H"
    "\x1b]0;claude - cloudecode\x07"
    "\x1b[32m$\x1b[0m git status\r\n"
    "On branch master\r\n"
    "nothing to commit, working tree clean\r\n"
    "run_id=2026 files=17 elapsed=3.4s\r\n"
)


def run(chunks: Sequence[str], **kwargs: object) -> str:
    redactor = StreamRedactor(**kwargs)  # type: ignore[arg-type]
    out = [redactor.feed(chunk) for chunk in chunks]
    out.append(redactor.flush(end=True))
    return "".join(out)


def split_every(text: str, size: int) -> List[str]:
    return [text[i:i + size] for i in range(0, len(text), size)]


def test_fixtures_are_really_detected() -> None:
    expected = {
        GITHUB: DETECTOR_GITHUB_TOKEN,
        AWS_KEY_ID: DETECTOR_AWS_ACCESS_KEY_ID,
        SLACK: DETECTOR_SLACK_TOKEN,
        ASSIGNMENT: DETECTOR_HIGH_ENTROPY_ASSIGNMENT,
    }
    for fixture, detector in expected.items():
        findings = scan_text(fixture)
        assert len(findings) == 1, f"fixture no longer detected: {detector}"
        assert findings[0].detector == detector
    assert not scan_text(ORDINARY), "the negative control carries a secret"



LENGTH_CASES: List[Sequence[str]] = [
    [],
    [""],
    ["", "", ""],
    ["hello world"],
    [ORDINARY],
    split_every(ORDINARY, 1),
    split_every(ORDINARY, 7),
    [GITHUB],
    split_every(GITHUB, 1),
    split_every(GITHUB, 3),
    ["prefix " + GITHUB + " suffix"],
    [ORDINARY + GITHUB + ORDINARY + AWS_KEY_ID + ORDINARY],
    split_every(ORDINARY + GITHUB + ASSIGNMENT + SLACK, 11),
    ["arabesque éèê", "日本語 " + SLACK],
    ["\x1b[31m" + GITHUB + "\x1b[0m"],
    [GITHUB[:5], "\x1b[1m", GITHUB[5:]],
]


@pytest.mark.parametrize("chunks", LENGTH_CASES, ids=range(len(LENGTH_CASES)))
def test_length_is_preserved_exactly(chunks: Sequence[str]) -> None:
    assert len(run(chunks)) == len("".join(chunks))


@pytest.mark.parametrize("tail", [1, 3, 16, 512, 4096])
def test_length_is_preserved_at_every_tail_size(tail: int) -> None:
    stream = ORDINARY + GITHUB + " " + ASSIGNMENT + ORDINARY
    for width in (1, 2, 13, 64, 10_000):
        out = run(split_every(stream, width), tail_bytes=tail)
        assert len(out) == len(stream), f"tail={tail} width={width}"


def test_redaction_replaces_one_character_with_one_star() -> None:
    out = run(["<" + GITHUB + ">"])
    assert out == "<" + REDACTION_CHAR * len(GITHUB) + ">"



@pytest.mark.parametrize("cut", [1, 4, 5, 20, 39])
def test_secret_split_across_two_feeds_is_caught(cut: int) -> None:
    out = run([GITHUB[:cut], GITHUB[cut:]])
    assert GITHUB not in out
    assert out == REDACTION_CHAR * len(GITHUB)


def test_secret_arriving_one_character_at_a_time() -> None:
    out = run(list(ORDINARY + GITHUB + ORDINARY))
    assert GITHUB not in out
    assert REDACTION_CHAR * len(GITHUB) in out


def test_flush_releases_the_held_tail() -> None:
    redactor = StreamRedactor(tail_bytes=8)
    first = redactor.feed("abcd efghij ")
    assert first == "abcd"
    assert redactor.flush() == " efghij "
    assert redactor.flush() == ""


def test_secret_held_in_the_tail_is_already_starred() -> None:
    redactor = StreamRedactor(tail_bytes=512)
    assert redactor.feed(GITHUB) == ""
    assert redactor.flush(end=True) == REDACTION_CHAR * len(GITHUB)



def test_escape_in_the_middle_of_a_token_does_not_defeat_detection() -> None:
    raw = GITHUB[:16] + "\x1b[31m" + GITHUB[16:]
    out = run([raw])
    assert out == (
        REDACTION_CHAR * 16 + "\x1b[31m" + REDACTION_CHAR * (len(GITHUB) - 16)
    )


def test_escape_bytes_inside_a_redacted_span_are_untouched() -> None:
    raw = GITHUB[:10] + "\x1b]0;window title\x07" + GITHUB[10:]
    out = run([raw])
    assert "\x1b]0;window title\x07" in out
    assert GITHUB[:10] not in out
    assert GITHUB[10:] not in out


@pytest.mark.parametrize(
    "escape",
    [
        "\x1b[31m",
        "\x1b[2;7H",
        "\x1b[?25l",
        "\x1b]0;title\x07",
        "\x1b]8;;url\x1b\\",
        "\x1bM",
        "\x1b7",
        "\x1b=",
    ],
)
def test_every_escape_shape_is_transparent_to_detection(escape: str) -> None:
    raw = AWS_KEY_ID[:7] + escape + AWS_KEY_ID[7:]
    out = run([raw])
    assert escape in out
    assert AWS_KEY_ID[:7] not in out
    assert out == (
        REDACTION_CHAR * 7 + escape
        + REDACTION_CHAR * (len(AWS_KEY_ID) - 7)
    )


def test_a_token_in_a_window_title_is_redacted() -> None:
    out = run(["\x1b]0;" + GITHUB + "\x07ok\n"])
    assert out == "\x1b]0;" + REDACTION_CHAR * len(GITHUB) + "\x07ok\n"


def test_a_token_in_a_hyperlink_target_is_redacted() -> None:
    link = "\x1b]8;;https://example.org/cb?t=" + GITHUB + "\x1b\\"
    out = run([link + "click\x1b]8;;\x1b\\\n"])
    assert GITHUB not in out
    assert out == (
        "\x1b]8;;https://example.org/cb?t=" + REDACTION_CHAR * len(GITHUB)
        + "\x1b\\click\x1b]8;;\x1b\\\n"
    )


def test_a_clipboard_write_payload_is_starred_whole() -> None:
    data = base64.b64encode(("copied " + AWS_KEY_ID).encode()).decode()
    out = run(["\x1b]52;c;" + data + "\x07"])
    assert out == "\x1b]52;c;" + REDACTION_CHAR * len(data) + "\x07"


def test_a_title_with_no_secret_passes_through_byte_identical() -> None:
    title = "\x1b]0;claude - cloudecode - ~/src\x07\x1b]2;vim\x1b\\$ "
    assert run([title]) == title
    assert run(split_every(title, 3)) == title


@pytest.mark.parametrize("cut", [3, 6, 15])
def test_an_osc_split_across_feeds_is_still_redacted(cut: int) -> None:
    raw = "\x1b]0;title " + GITHUB + "\x07$ "
    cut += len("\x1b]0;title ")
    redactor = StreamRedactor()
    out = redactor.feed(raw[:cut]) + redactor.flush()
    out += redactor.feed(raw[cut:]) + redactor.flush()
    assert GITHUB[cut - 11:] not in out
    assert out == "\x1b]0;title " + REDACTION_CHAR * len(GITHUB) + "\x07$ "


def test_an_escape_split_across_feeds_is_not_classified_early() -> None:
    out = run(["text \x1b[", "31m more text"])
    assert out == "text \x1b[31m more text"


def test_pure_escape_chunk_passes_through_byte_identical() -> None:
    escapes = "\x1b[2J\x1b[H\x1b]0;t\x07\x1bM\x1b[?25l"
    assert run([escapes]) == escapes
    assert run(split_every(escapes, 1)) == escapes



def _all_strings(obj: object, seen: Iterable[int] = ()) -> List[str]:
    visited = set(seen)
    if id(obj) in visited:
        return []
    visited.add(id(obj))
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        found: List[str] = []
        for key, value in obj.items():
            found += _all_strings(key, visited) + _all_strings(value, visited)
        return found
    if isinstance(obj, (list, tuple, set, frozenset)):
        found = []
        for item in obj:
            found += _all_strings(item, visited)
        return found
    inner = getattr(obj, "__dict__", None)
    if inner is not None:
        return _all_strings(inner, visited)
    return []


def test_the_value_never_escapes_onto_the_instance_or_its_stats() -> None:
    redactor = StreamRedactor()
    for chunk in (ORDINARY, GITHUB + " ", ASSIGNMENT):
        out = redactor.feed(chunk)
        assert GITHUB not in out
        assert ASSIGNMENT_VALUE not in out
        for text in _all_strings(redactor):
            assert GITHUB not in text, "a complete credential is parked"
            assert ASSIGNMENT_VALUE not in text, "a complete value is parked"
    tail = redactor.flush()
    assert GITHUB not in tail
    assert ASSIGNMENT_VALUE not in tail

    for text in _all_strings(redactor):
        assert GITHUB not in text
        assert ASSIGNMENT_VALUE not in text

    stats = redactor.stats
    for rendering in (repr(stats), str(stats), repr(redactor.stats.detectors)):
        assert GITHUB not in rendering
        assert ASSIGNMENT_VALUE not in rendering

    assert isinstance(stats, RedactionStats)
    assert set(vars(stats)) == {"chunks_in", "findings", "detectors"}


def test_stats_report_counts_and_detector_names_only() -> None:
    redactor = StreamRedactor()
    redactor.feed(GITHUB + "\n" + AWS_KEY_ID + "\n" + SLACK)
    redactor.feed("")
    redactor.flush()
    stats = redactor.stats
    assert stats.chunks_in == 2
    assert stats.findings == 3
    assert stats.detectors == tuple(sorted({
        DETECTOR_GITHUB_TOKEN,
        DETECTOR_AWS_ACCESS_KEY_ID,
        DETECTOR_SLACK_TOKEN,
    }))
    assert isinstance(stats.findings, int)


def test_a_finding_is_counted_once_not_once_per_rescan() -> None:
    redactor = StreamRedactor(tail_bytes=512)
    redactor.feed(GITHUB)
    for _ in range(5):
        redactor.feed("x")
    redactor.flush()
    assert redactor.stats.findings == 1


def test_an_unknown_detector_name_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="unknown detector"):
        StreamRedactor(detectors=["not_a_detector"])
    with pytest.raises(ValueError, match="tail_bytes"):
        StreamRedactor(tail_bytes=0)
    with pytest.raises(ValueError, match="max_buffer"):
        StreamRedactor(max_buffer=0)


def test_detector_narrowing_is_honoured() -> None:
    out = run([GITHUB + " " + AWS_KEY_ID], detectors=[DETECTOR_GITHUB_TOKEN])
    assert GITHUB not in out
    assert AWS_KEY_ID in out



def test_an_unterminated_escape_cannot_grow_the_buffer() -> None:
    redactor = StreamRedactor(tail_bytes=16, max_buffer=64)
    total_in = 0
    total_out = 0
    total_in += len("\x1b]0;")
    total_out += len(redactor.feed("\x1b]0;"))
    for _ in range(40):
        chunk = "filler-" * 40
        total_in += len(chunk)
        total_out += len(redactor.feed(chunk))
        assert len(redactor._buf) <= 64, "buffer grew past max_buffer"
    total_out += len(redactor.flush(end=True))
    assert total_out == total_in


def test_a_tail_wider_than_the_ceiling_is_capped_by_the_ceiling() -> None:
    redactor = StreamRedactor(tail_bytes=4096, max_buffer=128)
    for _ in range(20):
        redactor.feed("abcdefghij" * 50)
        assert len(redactor._buf) <= 128, "buffer grew past max_buffer"
    redactor.flush()
    assert redactor._buf == ""


def test_a_single_oversized_chunk_leaves_a_bounded_buffer() -> None:
    text = "".join(f"build line {i} ok\n" for i in range(12_000))
    redactor = StreamRedactor(tail_bytes=512, max_buffer=1024)
    out = redactor.feed(text)
    assert len(redactor._buf) <= 1024
    assert out + redactor.flush() == text


def test_a_long_unbroken_word_run_costs_linear_time() -> None:
    import time

    stream = "z" * 20_000 + " " + GITHUB + " " + "z" * 20_000
    started = time.monotonic()
    out = run([stream])
    elapsed = time.monotonic() - started
    assert GITHUB not in out
    assert len(out) == len(stream)
    assert elapsed < 60, f"scan took {elapsed:.1f}s"



def test_the_redactor_is_fully_usable_after_flush() -> None:
    redactor = StreamRedactor()
    parts: List[str] = []
    stream = ""
    for piece in (ORDINARY, GITHUB + "\n", ORDINARY):
        stream += piece
        parts.append(redactor.feed(piece))
        parts.append(redactor.flush())
    for piece in split_every(" " + AWS_KEY_ID + " ", 4):
        stream += piece
        parts.append(redactor.feed(piece))
    parts.append(redactor.flush())
    out = "".join(parts)
    assert len(out) == len(stream)
    assert GITHUB not in out
    assert AWS_KEY_ID not in out
    assert redactor.stats.detectors == tuple(sorted(
        (DETECTOR_AWS_ACCESS_KEY_ID, DETECTOR_GITHUB_TOKEN)
    ))
    tail_feeds = len(split_every(" " + AWS_KEY_ID + " ", 4))
    assert redactor.stats.chunks_in == 3 + tail_feeds


def test_a_token_cut_by_an_idle_flush_shows_neither_half() -> None:
    redactor = StreamRedactor()
    out = redactor.feed("token=" + GITHUB[:20]) + redactor.flush()
    out += redactor.feed(GITHUB[20:] + "\n") + redactor.flush()
    assert GITHUB[:20] not in out
    assert GITHUB[20:] not in out
    assert out == "token=" + REDACTION_CHAR * len(GITHUB) + "\n"


def test_an_undetectable_head_is_held_by_an_idle_flush() -> None:
    redactor = StreamRedactor()
    out = redactor.feed("$ echo " + GITHUB[:8])
    out += redactor.flush()
    assert GITHUB[:8] not in out
    out += redactor.feed(GITHUB[8:] + "\n") + redactor.flush()
    assert out == "$ echo " + REDACTION_CHAR * len(GITHUB) + "\n"


def test_a_quiet_prompt_is_released_whole_by_an_idle_flush() -> None:
    redactor = StreamRedactor()
    stream = "\x1b[32muser@host\x1b[0m:~/src$ "
    assert redactor.feed(stream) + redactor.flush() == stream
    assert redactor._buf == ""


def test_a_long_unbroken_run_is_released_by_an_idle_flush() -> None:
    redactor = StreamRedactor()
    stream = "=" * 300
    assert redactor.feed(stream) + redactor.flush() == stream


def test_an_open_key_block_stays_open_across_a_flush() -> None:
    block, body = pem_block(lines=12)
    stream = "before\n" + block + "after\n"
    cut_a = stream.index(body[3])
    cut_b = stream.index(body[8])
    redactor = StreamRedactor()
    out = ""
    for piece in (stream[:cut_a], stream[cut_a:cut_b], stream[cut_b:]):
        for part in split_every(piece, 13):
            out += redactor.feed(part)
        out += redactor.flush()
    for line in body:
        assert line not in out, "a body line after a flush reached the viewer"
    assert len(out) == len(stream)
    assert out.startswith("before\n")
    assert out.endswith("after\n"), "the region never closed after a flush"
    redactor.feed("plain text again\n")
    assert redactor.flush() == "plain text again\n"



def test_ordinary_output_passes_through_byte_identical() -> None:
    for width in (1, 3, 17, 1024):
        assert run(split_every(ORDINARY, width)) == ORDINARY
    assert run([ORDINARY], tail_bytes=1) == ORDINARY
    redactor = StreamRedactor()
    redactor.feed(ORDINARY)
    redactor.flush()
    assert redactor.stats.findings == 0
    assert redactor.stats.detectors == ()


def test_empty_input() -> None:
    redactor = StreamRedactor()
    assert redactor.feed("") == ""
    assert redactor.flush() == ""
    assert redactor.stats == RedactionStats(
        chunks_in=1, findings=0, detectors=()
    )
    assert run([]) == ""


def test_multiple_secrets_in_one_chunk() -> None:
    raw = f"a {GITHUB} b {AWS_KEY_ID} c {SLACK} d"
    out = run([raw])
    assert out == (
        f"a {REDACTION_CHAR * len(GITHUB)} "
        f"b {REDACTION_CHAR * len(AWS_KEY_ID)} "
        f"c {REDACTION_CHAR * len(SLACK)} d"
    )
    assert len(out) == len(raw)


def test_a_secret_at_the_very_start_and_at_the_very_end() -> None:
    raw = GITHUB + " middle " + AWS_KEY_ID
    out = run(split_every(raw, 9))
    assert out == (
        REDACTION_CHAR * len(GITHUB) + " middle "
        + REDACTION_CHAR * len(AWS_KEY_ID)
    )


def test_unicode_is_not_corrupted() -> None:
    text = "café 日本語 ñandú über"
    assert run([text]) == text
    assert run(split_every(text, 1)) == text
    out = run([text + " " + GITHUB + " " + text])
    assert out == text + " " + REDACTION_CHAR * len(GITHUB) + " " + text



def pem_block(label: str = "RSA", lines: int = 8) -> Tuple[str, List[str]]:
    body = [
        base64.b64encode(secrets.token_bytes(48)).decode()
        for _ in range(lines)
    ]
    block = (
        f"-----BEGIN {label} PRIVATE KEY-----\n"
        + "\n".join(body)
        + f"\n-----END {label} PRIVATE KEY-----\n"
    )
    return block, body


def minisign_block() -> Tuple[str, str]:
    body = base64.b64encode(secrets.token_bytes(74)).decode()
    return (
        "untrusted comment: minisign encrypted secret key\n" + body + "\n",
        body,
    )


def test_a_key_block_finding_covers_the_body_not_just_the_header() -> None:
    block, body = pem_block()
    findings = scan_text(block)
    assert [f.detector for f in findings] == [DETECTOR_PEM_PRIVATE_KEY]
    assert findings[0].length < len(block) // 4, (
        "the detector is expected to report the HEADER only; if it now "
        "reports the whole block this test's premise has changed"
    )

    out = run([block])
    for line in body:
        assert line not in out, "a key body line reached the viewer"
    assert "-----BEGIN" not in out
    assert "-----END" not in out
    assert len(out) == len(block)


@pytest.mark.parametrize("width", [1, 7, 29, 300, 100_000])
def test_a_key_block_split_across_feeds_is_fully_redacted(width: int) -> None:
    block, body = pem_block(label="EC", lines=40)
    stream = "before the key\n" + block + "after the key\n"
    out = run(split_every(stream, width))
    for line in body:
        assert line not in out
    assert len(out) == len(stream)
    assert out.startswith("before the key\n"), "innocent text was starred"
    assert out.endswith("after the key\n"), "the region never closed"
    assert out.count("\n") == stream.count("\n"), "line structure changed"


@pytest.mark.parametrize(
    "tail,ceiling", [(512, 65536), (128, 1024), (64, 256), (512, 600)]
)
def test_a_key_block_survives_every_bound(tail: int, ceiling: int) -> None:
    block, body = pem_block(label="OPENSSH", lines=60)
    stream = "start\n" + block + "end\n"
    assert len(block) > tail, "the block must outlive the tail"
    out = run(split_every(stream, 23), tail_bytes=tail, max_buffer=ceiling)
    for line in body:
        assert line not in out
    assert len(out) == len(stream)
    assert out.startswith("start\n")
    assert out.endswith("end\n")


@pytest.mark.parametrize("width", [1, 11, 100_000])
def test_a_minisign_secret_key_body_is_redacted(width: int) -> None:
    block, body = minisign_block()
    stream = "head\n" + block + "trailing line\n"
    redactor = StreamRedactor()
    out = "".join(
        redactor.feed(part) for part in split_every(stream, width)
    ) + redactor.flush()
    assert body not in out
    assert "untrusted comment" not in out
    assert len(out) == len(stream)
    assert out.startswith("head\n")
    assert out.endswith("trailing line\n"), "the two-line region overran"
    assert redactor.stats.detectors == (DETECTOR_MINISIGN_SECRET_KEY,)


def test_a_key_block_with_no_terminator_is_redacted_to_the_end() -> None:
    _, body = pem_block(lines=10)
    stream = "-----BEGIN RSA PRIVATE KEY-----\n" + "\n".join(body) + "\n"
    out = run(split_every(stream, 17))
    for line in body:
        assert line not in out
    assert len(out) == len(stream)


def test_newlines_inside_a_redacted_block_are_preserved() -> None:
    block, _ = pem_block(lines=5)
    out = run([block])
    assert out.count("\n") == block.count("\n")
    assert set(out) <= {REDACTION_CHAR, "\n"}


def test_the_assignment_name_survives_and_only_the_value_is_starred() -> None:
    out = run([ASSIGNMENT])
    assert out == "api_key = " + REDACTION_CHAR * len(ASSIGNMENT_VALUE)
