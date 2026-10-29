
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

from src.core.message_model_secrets import ALL_DETECTORS, SecretFinding
from src.core.stream_redactor_ansi import REDACTION_CHAR
from src.core.stream_redactor_detect import REGION_DETECTORS, _StarredSpan
from src.core.stream_redactor_text import _OpenRegion, _process

__all__ = [
    "REDACTION_CHAR",
    "REGION_DETECTORS",
    "DEFAULT_TAIL_BYTES",
    "DEFAULT_MAX_BUFFER",
    "RedactionStats",
    "StreamRedactor",
]

DEFAULT_TAIL_BYTES: int = 512

DEFAULT_MAX_BUFFER: int = 65536


@dataclass(frozen=True)
class RedactionStats:

    chunks_in: int
    findings: int
    detectors: Tuple[str, ...]

class StreamRedactor:

    def __init__(
        self,
        *,
        tail_bytes: int = DEFAULT_TAIL_BYTES,
        max_buffer: int = DEFAULT_MAX_BUFFER,
        detectors: Optional[Iterable[str]] = None,
    ) -> None:
        if tail_bytes < 1:
            raise ValueError("tail_bytes must be at least 1")
        if max_buffer < 1:
            raise ValueError("max_buffer must be at least 1")

        selected: Optional[Tuple[str, ...]] = None
        if detectors is not None:
            selected = tuple(detectors)
            unknown = frozenset(selected) - frozenset(ALL_DETECTORS)
            if unknown:
                raise ValueError(f"unknown detector(s): {sorted(unknown)!r}")

        self._tail_bytes = tail_bytes
        self._max_buffer = max_buffer
        self._detectors = selected
        self._buf = ""
        self._region: Optional[_OpenRegion] = None
        self._osc_open = False
        self._at_word_start = True
        self._context = ""
        self._starred_spans: Tuple[_StarredSpan, ...] = ()
        self._chunks_in = 0
        self._findings = 0
        self._fired: set[str] = set()

    def feed(self, chunk: str) -> str:
        self._chunks_in += 1
        if not chunk:
            return ""

        out: List[str] = []
        for base in range(0, len(chunk), self._max_buffer):
            self._buf += chunk[base:base + self._max_buffer]
            out.append(self._run(final=False, hold_word=False))
        return "".join(out)

    def flush(self, *, end: bool = False) -> str:
        if not self._buf:
            return ""
        return self._run(final=True, hold_word=not end)

    @property
    def stats(self) -> RedactionStats:
        return RedactionStats(
            chunks_in=self._chunks_in,
            findings=self._findings,
            detectors=tuple(sorted(self._fired)),
        )

    def _run(self, *, final: bool, hold_word: bool) -> str:
        result = _process(
            self._buf,
            detectors=self._detectors,
            open_region=self._region,
            in_osc=self._osc_open,
            tail_bytes=self._tail_bytes,
            max_buffer=self._max_buffer,
            final=final,
            hold_word=hold_word,
            at_word_start=self._at_word_start,
            context=self._context,
            starred_spans=self._starred_spans,
        )
        if result.word_boundary is not None:
            self._at_word_start = result.word_boundary
        self._region = result.open_region
        self._osc_open = result.osc_open
        self._context = result.context
        self._starred_spans = result.starred_spans
        self._record(result.findings)
        out = result.text[:result.release]
        self._buf = result.text[result.release:]
        return out

    def _record(self, findings: Sequence[SecretFinding]) -> None:
        if not findings:
            return
        self._findings += len(findings)
        for finding in findings:
            self._fired.add(finding.detector)


def redact_whole(text: str) -> str:
    redactor = StreamRedactor()
    return redactor.feed(text) + redactor.flush(end=True)
