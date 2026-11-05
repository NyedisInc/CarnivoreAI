
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterator, Optional, Set, Tuple

from src.cplugs.reviewboard import office_text as limits
from src.cplugs.reviewboard.pdf_streams import PdfUnreadable
from src.cplugs.sdk.file_secrets import Deadline

MIN_TOKENS = 2_000_000
TOKENS_PER_INPUT_BYTE = 1
CHECK_EVERY = 2048
MAX_NUMBER_CHARS = 40
REASON_SYNTAX = "malformed_pdf"

WHITESPACE = rb"\x00\t\n\x0c\r "
_REGULAR = rb"[^" + WHITESPACE + rb"()<>\[\]{}/%]"
HEADER_WHITESPACE = WHITESPACE + rb"\x0b"
SEPARATOR = rb"(?:[" + HEADER_WHITESPACE + rb"]|%[^\r\n]*+)++"
_HEADER_REGULAR = rb"[^" + HEADER_WHITESPACE + rb"()<>\[\]{}/%]"
_HEADER_TOKEN = re.compile(rb"(?P<sep>" + SEPARATOR + rb")|(?P<int>[+-]?[0-9]++|[+-])|(?P<obj>obj(?!" + _HEADER_REGULAR + rb"))|(?P<other>[^" + HEADER_WHITESPACE
                           + rb"%0-9+\-o]++|o)")


def find_headers(data: bytes, deadline: Deadline) -> Iterator[Tuple[int, int, int]]:
    prev: Optional[Tuple[int, int]] = None
    last: Optional[Tuple[int, int]] = None
    for count, match in enumerate(_HEADER_TOKEN.finditer(data)):
        if count % CHECK_EVERY == 0:
            deadline.check()
        kind = match.lastgroup
        if kind == "int":
            prev, last = last, (match.start(), match.end() - match.start())
        elif kind == "obj":
            if prev is not None and last is not None:
                yield prev[0], prev[1], last[1]
            prev = last = None
        elif kind == "sep":
            pass
        else:
            prev = last = None


_TOKEN = re.compile(rb"""
    (?P<ws>[\x00\t\n\x0c\r ]+|%[^\r\n]*)
  | (?P<name>/""" + _REGULAR + rb"""*)
  | (?P<dopen><<) | (?P<dclose>>>)
  | (?P<hex><[^<>]*>)
  | (?P<lit>\()
  | (?P<aopen>\[) | (?P<aclose>\])
  | (?P<num>[+-]?(?:\d+\.?\d*|\.\d+))(?=[\x00\t\n\x0c\r ()<>\[\]{}/%]|$)
  | (?P<kw>""" + _REGULAR + rb"""+)
  | (?P<stray>[<>(){}])
""", re.X)
_LIT_EDGE = re.compile(rb"[()\\]")
_ESCAPE = re.compile(rb"#([0-9A-Fa-f]{2})")

Token = Tuple[str, object, int]


@dataclass
class Meter:

    deadline: Deadline
    tokens_left: int = field(default_factory=lambda: MIN_TOKENS)

    @classmethod
    def for_input(cls, deadline: Deadline, size: int) -> "Meter":
        return cls(deadline, max(MIN_TOKENS, TOKENS_PER_INPUT_BYTE * size))


class Lexer:

    def __init__(self, data: bytes, meter: Meter, pos: int = 0) -> None:
        self.data: bytes = data
        self.meter: Meter = meter
        self.pos: int = pos
        self.names: Set[str] = set()
        self._count = 0

    def _spend(self) -> None:
        self.meter.tokens_left -= 1
        if self.meter.tokens_left < 0:
            raise PdfUnreadable(limits.REASON_TOO_BIG)
        self._count += 1
        if self._count % CHECK_EVERY == 0:
            self.meter.deadline.check()

    def _literal_end(self, start: int) -> int:
        depth, pos = 1, start + 1
        while depth:
            edge = _LIT_EDGE.search(self.data, pos)
            if edge is None:
                raise PdfUnreadable(REASON_SYNTAX)
            char = edge.group()
            pos = edge.end() + (1 if char == b"\\" else 0)
            depth += 1 if char == b"(" else -1 if char == b")" else 0
        return pos

    def next(self) -> Optional[Token]:
        data = self.data
        while True:
            match = _TOKEN.match(data, self.pos)
            if match is None:
                if self.pos >= len(data):
                    return None
                raise PdfUnreadable(REASON_SYNTAX)
            kind, start = match.lastgroup, self.pos
            self.pos = match.end()
            if kind == "ws":
                continue
            self._spend()
            if kind == "lit":
                self.pos = self._literal_end(start)
                return ("str", data[start:self.pos], start)
            if kind == "name":
                raw = match.group()[1:]
                name = (_ESCAPE.sub(lambda m: bytes([int(m.group(1), 16)]), raw) if b"#" in raw else raw).decode("latin-1")
                self.names.add(name)
                return ("name", name, start)
            if kind == "num":
                text = match.group()
                if len(text) > MAX_NUMBER_CHARS:
                    raise PdfUnreadable(REASON_SYNTAX)
                return ("int", int(text), start) if text.lstrip(b"+-").isdigit() else ("real", float(text), start)
            if kind == "stray":
                raise PdfUnreadable(REASON_SYNTAX)
            if kind == "hex":
                return ("str", match.group(), start)
            return ({"dopen": "<<", "dclose": ">>", "aopen": "[", "aclose": "]"}.get(kind) or "kw", match.group(), start)
