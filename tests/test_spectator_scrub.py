
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.core import spectator_redaction

MARKER = "CLOUDE-FAKE-CREDENTIAL-MARKER"
CHUNK = ("before " + MARKER + " after-the-marker").encode()
STARRED = ("before " + "*" * len(MARKER) + " after-the-marker").encode()


class _StarringRedactor:

    def __init__(self, hold: int = 0) -> None:
        self._buf = ""
        self._hold = hold
        self._chunks = 0
        self._findings = 0

    def feed(self, chunk: str) -> str:
        self._chunks += 1
        self._buf += chunk
        self._findings += self._buf.count(MARKER)
        self._buf = self._buf.replace(MARKER, "*" * len(MARKER))
        cut = max(len(self._buf) - self._hold, 0)
        out, self._buf = self._buf[:cut], self._buf[cut:]
        return out

    def flush(self) -> str:
        out, self._buf = self._buf, ""
        return out

    @property
    def stats(self):
        return SimpleNamespace(
            chunks_in=self._chunks, findings=self._findings,
            detectors=("test_marker",) if self._findings else (),
        )




def test_a_split_utf8_character_and_a_non_utf8_byte_pass_through_exactly():
    scrubber = spectator_redaction.build_scrubber(label="t", factory=_StarringRedactor)
    raw = "café ☃ ".encode() + b"\xff\xfe" + b" end"
    out = b"".join(scrubber.scrub(raw[i:i + 1]) for i in range(len(raw)))
    out += scrubber.flush(final=True)
    assert out == raw


def test_a_flush_leaves_the_same_redactor_feeding():
    scrubber = spectator_redaction.build_scrubber(
        label="t", factory=lambda: _StarringRedactor(hold=5))
    first = scrubber.scrub(b"hello world")
    first += scrubber.flush()
    assert first == b"hello world" and not scrubber.pending
    assert scrubber.scrub(MARKER.encode()) + scrubber.flush() == b"*" * len(MARKER)


def test_the_real_redactor_stars_a_token_in_the_scrubbed_stream():
    pytest.importorskip("src.core.stream_redactor")
    alphabet = "aB3dE5fG7hJ9kL1mN2pQ4rS6tU8vW0xY2zA4cD6e"
    token = "gh" + "p_" + alphabet[:36]
    chunk = f"export GH={token} done-marker\r\n".encode()
    assert token.encode() in chunk

    scrubber = spectator_redaction.build_scrubber(
        label="t", factory=spectator_redaction.default_redactor_factory)
    out = scrubber.scrub(chunk) + scrubber.flush(final=True)
    assert b"done-marker" in out and token.encode() not in out, out
